#!/usr/bin/env python3
"""Genera las tablas del README desde donde viven sus datos.

Tres tablas que se desfasaban cada vez que se tocaba un agente, un caso o un
puerto, porque estaban escritas a mano en el README y otra vez en el Makefile:

    casos     <- catalog/cases.yaml
    catálogo  <- catalog/agents/**/agent.yaml (+ en qué casos participa cada uno)
    uis       <- deploy/services.yaml

Cada una va entre marcadores ``<!-- BEGIN GENERADO: x -->`` y ``<!-- END GENERADO: x -->``;
lo de fuera no se toca. `make docs` la regenera y `make test` comprueba que está al día.

Uso:  python3 scripts/gen-readme-tables.py [--check]
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

import yaml

RAIZ = Path(__file__).resolve().parent.parent
README = RAIZ / "README.md"


def _celda(texto: str) -> str:
    return " ".join(str(texto).split()).replace("|", "\\|")


def _ui(texto: str | None) -> str:
    """`make dev-adk X  (pestaña Events)` -> código y, fuera, la aclaración."""
    if not texto or texto.startswith("http"):
        return texto or ""
    comando, _, resto = texto.partition("  (")
    if not comando.startswith(("make ", "docker ", "agentctl ", "tail ")):
        return _celda(texto)
    return f"`{comando}`" + (f" ({_celda(resto)}" if resto else "")


def tabla_casos() -> str:
    from agent_runtime.cases import load_cases

    filas = ["| # | Pruébalo | Qué colaboración ves | Míralo también en una UI |", "|---|---|---|---|"]
    for caso in load_cases(RAIZ):
        ui = _ui(caso.ui)
        if caso.ui and caso.ui.startswith("http") and "/chat" in caso.ui:
            ui = f"El [chat de `{caso.agent}`]({caso.ui}) en kagent"
        filas.append(f"| {caso.id} | `make caso-{caso.id}` | {_celda(caso.shows)} | {ui} |")
    return "\n".join(filas)


def tabla_catalogo() -> str:
    from agent_runtime import load_platform
    from agent_runtime.cases import cases_by_agent, load_cases

    factory = load_platform(root=RAIZ, environment="local", load_env_file=False, tracing=False)
    store = factory.store
    en_casos = cases_by_agent(factory, load_cases(RAIZ))

    filas = ["| Dominio | Agente | Para qué es | Usa | Casos |", "|---|---|---|---|---|"]
    agentes = sorted(store.list_agents(), key=lambda n: (store.domain_of(n) or "", n))
    for nombre in agentes:
        manifest = store.load(nombre)
        spec = manifest.spec
        usa = []
        if spec.enabled_tools:
            familias = sorted({t.ref.split(".")[0] for t in spec.enabled_tools})
            usa.append(", ".join(f"`{f}.*`" for f in familias))
        if spec.sandbox.enabled:
            usa.append("sandbox")
        if spec.enabled_skills:
            usa.append("skill " + ", ".join(f"`{s.ref.split('@')[0]}`" for s in spec.enabled_skills))
        if spec.enabled_sub_agents:
            usa.append("delega en " + ", ".join(f"`{s.ref}`" for s in spec.enabled_sub_agents))
        casos = ", ".join(map(str, en_casos.get(nombre, []))) or "—"
        filas.append(
            f"| {store.domain_of(nombre)} | `{nombre}` | {_celda(manifest.metadata.description)} "
            f"| {' · '.join(usa) or '—'} | {casos} |"
        )
    for nombre in store.list_workflows():
        manifest = store.load(nombre)
        pasos = " → ".join(f"`{n.agent}`" for n in manifest.spec.nodes)
        casos = ", ".join(map(str, en_casos.get(nombre, []))) or "—"
        filas.append(
            f"| workflow · {manifest.spec.type} | `{nombre}` | {_celda(manifest.metadata.description)} "
            f"| {pasos} | {casos} |"
        )
    return "\n".join(filas)


def tabla_uis() -> str:
    datos = yaml.safe_load((RAIZ / "deploy" / "services.yaml").read_text(encoding="utf-8"))
    filas = ["| UI | URL | Se levanta con | Para qué |", "|---|---|---|---|"]
    for servicio in datos["services"]:
        if "a2a" in servicio:
            entorno = RAIZ / "configs" / "environments" / f"{servicio['a2a']}.yaml"
            urls = list(((yaml.safe_load(entorno.read_text(encoding="utf-8")) or {}).get("a2a") or {})
                        .get("endpoints", {}).values())
            puertos = sorted(urlparse(u).port for u in urls)
            url = f"{urls[0]}.well-known/agent-card.json … :{puertos[-1]}" if urls else "—"
        else:
            url = servicio["url"]
        inicio = " · ".join(f"`{c.strip()}`" for c in servicio["start"].split(" · "))
        para = _celda(servicio["purpose"])
        if servicio.get("credentials"):
            para += f" ({_celda(servicio['credentials'])})"
        if servicio["lane"] == "gitops":
            para += " · sólo con `make gitops-lab`"
        filas.append(f"| **{servicio['name']}** | {url} | {inicio} | {para} |")
        for enlace in servicio.get("links") or []:
            filas.append(f"| └ {enlace['name']} | {enlace['url']} | | {_celda(enlace['purpose'])} |")
    return "\n".join(filas)


TABLAS = {"casos": tabla_casos, "catálogo": tabla_catalogo, "uis": tabla_uis}


def render(texto: str) -> str:
    for nombre, generar in TABLAS.items():
        patron = re.compile(
            rf"(<!-- BEGIN GENERADO: {nombre} [^>]*-->\n)(?:.*?\n)?(<!-- END GENERADO: {nombre} -->)", re.S
        )
        if not patron.search(texto):
            raise SystemExit(f"README.md no tiene los marcadores de la tabla '{nombre}'")
        tabla = generar()
        texto = patron.sub(lambda m: m.group(1) + tabla + "\n" + m.group(2), texto)
    return texto


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="Falla si el README no está al día")
    args = parser.parse_args()

    actual = README.read_text(encoding="utf-8")
    nuevo = render(actual)
    if args.check:
        if nuevo != actual:
            print("README.md desfasado respecto a catalog/cases.yaml, los manifiestos o deploy/services.yaml: make docs",
                  file=sys.stderr)
            return 1
        return 0
    if nuevo != actual:
        README.write_text(nuevo, encoding="utf-8")
        print(f"  {README.relative_to(RAIZ)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
