#!/usr/bin/env python3
"""Qué está levantado de la plataforma, y cómo parar lo local.

    stack.py status [--links]   cada servicio de deploy/services.yaml: ✓ con su URL, o ✗ con cómo levantarlo
    stack.py down [pid...]      para lo que los `make` dejaron en marcha en local (no toca el clúster)

Sólo librería estándar y PyYAML: tiene que funcionar antes de `make install` y
aunque no haya clúster. Todo lo que habla con Kubernetes va contra el contexto
del lab (KUBE_CONTEXT), nunca contra el activo.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

import yaml

ROOT = Path(__file__).resolve().parents[2]
SERVICES = ROOT / "deploy" / "services.yaml"
PIDS = ROOT / ".agent-platform" / "pids"
CLUSTER = os.getenv("CLUSTER", "agent-lab")
CONTEXT = os.getenv("KUBE_CONTEXT", f"kind-{CLUSTER}")

_TTY = sys.stdout.isatty() and not os.getenv("NO_COLOR")


def _paint(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _TTY else text


OK, KO = _paint("32", "✓"), _paint("31", "✗")
dim = lambda text: _paint("2", text)  # noqa: E731
bold = lambda text: _paint("1", text)  # noqa: E731


def load(path: Path = SERVICES) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


# -- sondas -------------------------------------------------------------------


def http_up(url: str, timeout: float = 1.5) -> bool:
    """Responde algo que no sea un error del servidor. Sin verificar TLS: es local."""
    context = ssl.create_default_context()
    context.check_hostname, context.verify_mode = False, ssl.CERT_NONE
    try:
        with urllib.request.urlopen(url, timeout=timeout, context=context) as response:
            return response.status < 500
    except urllib.error.HTTPError as exc:
        return exc.code < 500
    except (OSError, ValueError):
        return False


def a2a_endpoints(environment: str) -> dict[str, str]:
    path = ROOT / "configs" / "environments" / f"{environment}.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {str(k): str(v) for k, v in ((data.get("a2a") or {}).get("endpoints") or {}).items()}


def kubectl(*args: str) -> str | None:
    if not shutil.which("kubectl"):
        return None
    try:
        done = subprocess.run(
            ["kubectl", "--context", CONTEXT, "--request-timeout=3s", *args],
            capture_output=True, text=True, timeout=8,
        )
    except subprocess.TimeoutExpired:
        return None
    return done.stdout if done.returncode == 0 else None


def cluster_mode() -> str | None:
    """None si no hay clúster; si lo hay, quién gestiona la plataforma: helm, argocd o nadie aún."""
    if not shutil.which("kind"):
        return None
    clusters = subprocess.run(["kind", "get", "clusters"], capture_output=True, text=True).stdout.split()
    if CLUSTER not in clusters:
        return None
    if (kubectl("-n", "argocd", "get", "applications.argoproj.io", "-o", "name") or "").strip():
        return "argocd"
    if shutil.which("helm") and subprocess.run(
        ["helm", "--kube-context", CONTEXT, "status", "kagent", "-n", "kagent"], capture_output=True
    ).returncode == 0:
        return "helm"
    return "empty"


def ready_count(spec: str) -> tuple[int, int] | None:
    namespace, resource = spec.split("/", 1)
    out = kubectl("-n", namespace, "get", resource, "-o", "json")
    if out is None:
        return None
    items = json.loads(out).get("items", [])
    ready = sum(
        1 for item in items
        if any(c.get("type") == "Ready" and c.get("status") == "True"
               for c in (item.get("status") or {}).get("conditions") or [])
    )
    return ready, len(items)


def deployed(spec: str) -> bool:
    namespace, name = spec.split("/", 1)
    out = kubectl("-n", namespace, "get", "deployment", name, "-o", "jsonpath={.status.readyReplicas}")
    return bool(out and out.strip() not in ("", "0"))


# -- procesos que dejaron los make -------------------------------------------


def tracked(name: str, match: str | None) -> list[int]:
    """Los pids guardados con ese nombre (``<name>.pid``, ``<name>.<algo>.pid``) que siguen vivos.

    Uno en primer plano (make a2a-up) y otro en segundo (make caso-7) pueden
    convivir, así que puede haber varios. Si un pid ya no es lo que se lanzó
    (``match`` no está en su línea de comandos), se reutilizó y no es nuestro.
    """
    alive = []
    for path in sorted({*PIDS.glob(f"{name}.pid"), *PIDS.glob(f"{name}.*.pid")}):
        try:
            pid = int(path.read_text().split()[0])
            os.kill(pid, 0)
        except (OSError, ValueError, IndexError):
            path.unlink(missing_ok=True)
            continue
        if match and match not in _cmdline(pid):
            path.unlink(missing_ok=True)
            continue
        alive.append(pid)
    return alive


def _cmdline(pid: int) -> str:
    out = subprocess.run(["ps", "-o", "args=", "-p", str(pid)], capture_output=True, text=True).stdout
    return out.strip()


def _descendants(pid: int) -> list[int]:
    out = subprocess.run(["ps", "-eo", "pid=,ppid="], capture_output=True, text=True).stdout
    children: dict[int, list[int]] = {}
    for line in out.splitlines():
        child, parent = map(int, line.split())
        children.setdefault(parent, []).append(child)
    found, pending = [], [pid]
    while pending:
        for child in children.get(pending.pop(), []):
            found.append(child)
            pending.append(child)
    return found


def stop_tree(pid: int) -> None:
    """El proceso y todo lo que lanzó (agentctl ui -> adk web, npx -> node...)."""
    for target in [*reversed(_descendants(pid)), pid]:
        try:
            os.kill(target, signal.SIGTERM)
        except OSError:
            pass
    for _ in range(50):
        try:
            os.kill(pid, 0)
        except OSError:
            return
        time.sleep(0.1)
    for target in [pid, *_descendants(pid)]:
        try:
            os.kill(target, signal.SIGKILL)
        except OSError:
            pass


# -- status ---------------------------------------------------------------------


def _row(mark: str, name: str, where: str, hint: str = "") -> None:
    print(f"  {mark} {name:<22} {where:<44} {dim(hint)}".rstrip())


def _a2a_row(service: dict) -> bool:
    declared = a2a_endpoints(service["a2a"])
    up = [name for name, url in declared.items() if http_up(url.rstrip("/") + "/.well-known/agent-card.json")]
    ports = sorted(urlparse(url).port for url in declared.values())
    where = f"{len(up)}/{len(declared)} responden  :{ports[0]}-{ports[-1]}" if ports else "ninguno declarado"
    if up:
        _row(OK, service["name"], where, f"make a2a-cards · parar: {service.get('stop', 'Ctrl+C')}")
        missing = [name for name in declared if name not in up]
        if missing:
            print(f"    {dim('sin levantar: ' + ', '.join(missing) + '  (make a2a-catalog los levanta todos)')}")
    else:
        _row(KO, service["name"], where, service["start"])
    return bool(up)


def _service_row(service: dict, *, links: bool) -> bool:
    if "a2a" in service:
        return _a2a_row(service)

    up = http_up(service.get("health", service["url"]))
    pid = tracked(service["pid"], service.get("match")) if service.get("pid") else []
    extra = ""
    if "ready" in service:
        counted = ready_count(service["ready"])
        if counted is not None:
            ready, total = counted
            extra = f"{ready}/{total} agentes Ready" if total else "0 agentes: make deploy"

    if up:
        hint = extra or service.get("credentials") or ""
        if pid:
            hint = (hint + " · " if hint else "") + "parar: make down"
        elif service.get("pid"):
            hint = (hint + " · " if hint else "") + "no lo levantó make: otra terminal o el clúster"
        _row(OK, service["name"], service["url"], hint)
        if links:
            for link in service.get("links") or []:
                print(f"      {dim('└')} {link['name']:<24} {link['url']}")
    elif "deployment" in service and deployed(service["deployment"]):
        _row(KO, service["name"], "desplegado, pero no responde", service.get("expose", service["start"]))
    else:
        _row(KO, service["name"], "—", service["start"])
    return up


def status(links: bool = False) -> int:
    data = load()
    lanes = data["lanes"]
    services = data["services"]
    mode = cluster_mode()

    for lane, title in lanes.items():
        rows = [s for s in services if s["lane"] == lane]
        if lane == "cluster":
            if mode is None:
                print(f"\n{bold(title)}  {dim('no existe')}")
                _row(KO, f"clúster {CLUSTER}", "—", "make lab   (o make gitops-lab, con ArgoCD)")
                continue
            how = {"helm": "lo gestiona helm (make lab)", "argocd": "lo gestiona ArgoCD (make gitops-lab)",
                   "empty": "sin plataforma aún: make platform o make gitops-lab"}[mode]
            print(f"\n{bold(title)}  {dim(how)}")
        elif lane == "gitops":
            if mode != "argocd":
                print(f"\n{dim(title + ': ArgoCD y Grafana no están en este clúster')}")
                continue
            print(f"\n{bold(title)}")
        else:
            print(f"\n{bold(title)}")
        for service in rows:
            _service_row(service, links=links)

    print(f"\n  {dim('URLs de cada UI: make ui-urls · comprobar requisitos: make doctor · parar lo local: make down')}\n")
    return 0


def down(only: list[str] | None = None) -> int:
    """Parar lo que los make dejaron en marcha; ``only``: sólo esos pids (p. ej. a2a)."""
    stopped = 0
    for service in load()["services"]:
        name = service.get("pid")
        if not name or (only and name not in only):
            continue
        for pid in tracked(name, service.get("match")):
            stop_tree(pid)
            print(f"  parado: {service['name']} (pid {pid})")
            stopped += 1
        for path in [*PIDS.glob(f"{name}.pid"), *PIDS.glob(f"{name}.*.pid")]:
            path.unlink(missing_ok=True)
    if not stopped:
        print("  nada que parar que hayan levantado los make (lo de otras terminales: Ctrl+C allí)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    actions = parser.add_subparsers(dest="action", required=True)
    st = actions.add_parser("status")
    st.add_argument("--links", action="store_true", help="También las sub-páginas de cada UI")
    dn = actions.add_parser("down")
    dn.add_argument("only", nargs="*", help="Sólo estos (el campo pid de services.yaml), p. ej. a2a")
    args = parser.parse_args(argv)
    return status(links=args.links) if args.action == "status" else down(args.only)


if __name__ == "__main__":
    raise SystemExit(main())
