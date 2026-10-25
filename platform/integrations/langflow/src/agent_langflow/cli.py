"""``agentctl langflow``: the catalogue, in Langflow.

    agentctl --env local-a2a langflow agents              qué agentes puede llamar Langflow, y dónde
    agentctl --env local-a2a langflow export tech-article  el flujo, generado del YAML e importado
    agentctl --env local-a2a langflow export tech-article -o flow.json   sólo el fichero
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def register(sub: Any) -> None:
    langflow = sub.add_parser("langflow", help="Langflow as the console: flows generated from the catalogue, over A2A")
    actions = langflow.add_subparsers(dest="langflow_command", required=True)

    agents = actions.add_parser("agents", help="The catalogue agents Langflow can call, and their A2A URLs")
    agents.set_defaults(func=cmd_agents)

    export = actions.add_parser("export", help="Generate the Langflow flow of an agent or workflow and import it")
    export.add_argument("name", help="Agent or workflow of the catalogue")
    export.add_argument("-o", "--output", type=Path, help="Write the flow JSON here instead of importing it")
    export.add_argument("--url", help="Langflow URL (default: LANGFLOW_URL or http://127.0.0.1:7860)")
    export.add_argument("--timeout", type=int, default=300, help="Seconds each A2A node waits (default: 300)")
    export.add_argument("--run", metavar="MESSAGE", help="After importing, run the flow once with this message")
    export.set_defaults(func=cmd_export)


def cmd_agents(args: argparse.Namespace) -> int:
    from agent_runtime import load_platform

    factory = load_platform(root=args.root, environment=args.env)
    endpoints = factory.store.remote_agents
    if not endpoints:
        print(f"'{factory.environment}' declares no A2A endpoints: use --env local-a2a", file=sys.stderr)
        return 2
    for name in sorted(factory.store.list_agents()):
        url = endpoints.get(name)
        print(f"  {name:20} {url or '— (no se sirve por A2A en este entorno)'}")
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    from agent_core.errors import PlatformError
    from agent_runtime import load_platform

    from .client import Langflow
    from .export import export_flow

    factory = load_platform(root=args.root, environment=args.env)
    store = factory.store
    manifest = store.load(args.name)
    source = _source(store, manifest)
    try:
        langflow = Langflow(args.url, root=store.root)
        flow = export_flow(manifest, templates=langflow.catalogue(), endpoints=store.remote_agents,
                           source=source, timeout=args.timeout)
        if args.output:
            args.output.write_text(json.dumps(flow, indent=2, ensure_ascii=False), encoding="utf-8")
            print(f"  ✓ {args.output}  ({len(flow['data']['nodes'])} nodos, de {source})")
            return 0
        created = langflow.create_flow(flow)
        print(f"  ✓ '{flow['name']}' en Langflow: {langflow.url}/flow/{created['id']}  (de {source})")
        if args.run:
            # Each A2A node may take up to --timeout, one after another in the worst case.
            steps = sum(1 for n in flow["data"]["nodes"] if n["data"]["type"] == "A2AAgent")
            answer = langflow.run(created["id"], args.run, timeout=args.timeout * steps + 60)
            print(_answer_text(answer))
    except PlatformError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


def _source(store: Any, manifest: Any) -> str:
    if manifest.kind == "Agent":
        return str((store.agent_paths[manifest.name]).relative_to(store.root))
    return f"catalog/workflows/{manifest.name}.yaml"


def _answer_text(result: dict[str, Any]) -> str:
    """The chat text of a `/api/v1/run` answer."""
    try:
        outputs = result["outputs"][0]["outputs"][0]
        message = outputs.get("results", {}).get("message", {})
        return message.get("text") or message.get("data", {}).get("text") or json.dumps(outputs)[:2000]
    except (KeyError, IndexError, TypeError):
        return json.dumps(result)[:2000]
