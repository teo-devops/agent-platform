"""``agentctl kagent``: render the CRDs of a release, or host one BYO agent."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any

#: Defaults relative to the platform root.
RELEASE_FILE = "deploy/kagent/release.yaml"
OUTPUT_DIR = ".agent-platform/dist/kagent"
PROMPT_VERSIONS = ".agent-platform/dist/prompt-versions.json"


def register(sub: Any) -> None:
    kagent = sub.add_parser("kagent", help="Run catalogue agents on kagent (render CRDs, host BYO agents)")
    actions = kagent.add_subparsers(dest="kagent_command", required=True)

    render = actions.add_parser("render", help="Render the kagent CRDs of a release from the manifests")
    render.add_argument("-f", "--release", default=RELEASE_FILE, help=f"Release file (default: {RELEASE_FILE})")
    render.add_argument("-o", "--output", default=OUTPUT_DIR, help=f"Output directory (default: {OUTPUT_DIR})")
    render.add_argument(
        "--prompt-versions", default=PROMPT_VERSIONS,
        help="JSON {agent: version} from `agentctl mlflow prompts push` (optional)",
    )
    render.add_argument("--strict", action="store_true", help="Fail on warnings (unenforced guardrails...)")
    render.set_defaults(func=cmd_render)

    host = actions.add_parser("host", help="Serve one agent as a kagent BYO agent (runs inside the pod)")
    host.add_argument("name", nargs="?", default=os.getenv("AGENT"), help="Agent (default: $AGENT)")
    host.add_argument("--runtime", dest="host_runtime", default=os.getenv("AGENT_RUNTIME", "langgraph"))
    host.add_argument("--host", default="0.0.0.0")
    host.add_argument("--port", type=int, default=8080, help="kagent's BYO contract port")
    host.set_defaults(func=cmd_host)


def cmd_render(args: argparse.Namespace) -> int:
    from agent_runtime import load_platform

    from .release import Release
    from .render import load_prompt_versions, render

    probe = load_platform(root=args.root, environment=args.env, tracing=False)
    root = probe.store.root
    release = Release.load(_under(root, args.release))
    factory = probe if (args.env or probe.environment) == release.spec.environment else load_platform(
        root=root, environment=release.spec.environment, tracing=False
    )

    rendered = render(factory, release, prompt_versions=load_prompt_versions(_under(root, args.prompt_versions)))
    for warning in rendered.warnings:
        print(f"aviso: {warning}", file=sys.stderr)
    if args.strict and rendered.warnings:
        return 1

    for path in rendered.write(_under(root, args.output)):
        print(f"  {path.relative_to(root) if path.is_relative_to(root) else path}")
    agents = ", ".join(f"{a.name} ({a.mode})" for a in release.spec.agents)
    print(f"\n{len(release.spec.agents)} agente(s): {agents}\n"
          f"Aplica con: kubectl apply -k {args.output}")
    return 0


def cmd_host(args: argparse.Namespace) -> int:
    from .host import serve

    if not args.name:
        print("error: indica el agente, o define $AGENT", file=sys.stderr)
        return 2
    serve(args.name, runtime=args.host_runtime, environment=args.env, host=args.host, port=args.port)
    return 0


def _under(root: Path, path: str) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else root / candidate
