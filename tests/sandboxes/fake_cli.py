"""Un `sbx` / `openshell` de mentira para los tests: registra cada llamada y ejecuta `exec` aquí.

Lo instala `fake_cli()` en un directorio del PATH. Las rutas `/workspace` del
sandbox se traducen a un directorio temporal, así un test puede comprobar que el
backend escribe, lee y ejecuta lo que debe sin una microVM ni un gateway.
"""

from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path

SCRIPT = r'''#!{python}
import json, os, subprocess, sys
log, root, kind = {log!r}, {root!r}, {kind!r}
args = sys.argv[1:]
with open(log, "a") as fh:
    fh.write(json.dumps(args) + "\n")

def run(command, stdin):
    command = [c.replace("/workspace", root).replace("sudo ", "") for c in command]
    done = subprocess.run(command, input=stdin, capture_output=True, text=True)
    sys.stdout.write(done.stdout); sys.stderr.write(done.stderr); sys.exit(done.returncode)

stdin = sys.stdin.read() if not sys.stdin.isatty() else ""
if kind == "sbx":
    if args[:3] == ["policy", "inspect", "local-policy"]:
        print(os.environ.get("FAKE_SBX_GLOBAL", "allow      **         network            -      active"))
    elif args[0] == "exec":
        rest = args[2:]                       # exec -i [...]
        if rest[0] == "-w":
            rest = rest[2:]
        run(rest[1:], stdin)                  # rest[0] es el nombre del sandbox
else:
    if args[:2] == ["sandbox", "get"]:
        print(json.dumps({{"status": {{"phase": os.environ.get("FAKE_OPENSHELL_PHASE", "Ready")}}}}))
    elif args[:2] == ["sandbox", "create"]:
        policy = args[args.index("--policy") + 1]
        with open(log + ".policy", "w") as fh:
            fh.write(open(policy).read())
    elif args[:2] == ["sandbox", "exec"]:
        run(args[args.index("--") + 1:], stdin)
'''


def install(directory: Path, kind: str) -> tuple[Path, Path]:
    """Write the fake `kind` CLI into ``directory``; returns (log file, fake /workspace)."""
    root = directory / "workspace"
    root.mkdir()
    log = directory / "calls.jsonl"
    cli = directory / kind
    cli.write_text(SCRIPT.format(python=sys.executable, log=str(log), root=str(root), kind=kind))
    cli.chmod(cli.stat().st_mode | stat.S_IEXEC)
    return log, root


def calls(log: Path) -> list[list[str]]:
    return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []


def path_with(directory: Path) -> str:
    return f"{directory}{os.pathsep}{os.environ.get('PATH', '')}"
