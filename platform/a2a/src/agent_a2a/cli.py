"""``agentctl a2a``: serve catalogue agents over A2A, read a card, send a message."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import Any

from .server import DEFAULT_PORT


def register(sub: Any) -> None:
    a2a = sub.add_parser("a2a", help="Agents over A2A: serve them, read their card, talk to them")
    actions = a2a.add_subparsers(dest="a2a_command", required=True)

    serve = actions.add_parser(
        "serve",
        help="Serve one or more agents over A2A, one port each",
        description="Each agent is `name` or `name:framework` (python-developer:langgraph). "
                    "Ports are consecutive from --port.",
    )
    serve.add_argument("agents", nargs="+", metavar="agent[:framework]")
    serve.add_argument("--port", type=int, default=DEFAULT_PORT + 1, help=f"First port (default: {DEFAULT_PORT + 1})")
    serve.add_argument("--host", default="127.0.0.1", help="Use 0.0.0.0 inside a container")
    serve.add_argument("-v", "--verbose", action="store_true", help="Narrate the tool calls of each request")
    serve.set_defaults(func=cmd_serve)

    card = actions.add_parser("card", help="Print the agent card published at a URL")
    card.add_argument("url")
    card.set_defaults(func=cmd_card)

    send = actions.add_parser("send", help="Send one message to the agent at a URL (message/send)")
    send.add_argument("url")
    send.add_argument("-m", "--message", required=True)
    send.set_defaults(func=cmd_send)


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn
    from agent_runtime import load_platform

    from .server import build_app

    servers, participants = [], ({}, {})
    for offset, spec in enumerate(args.agents):
        name, _, framework = spec.partition(":")
        factory = load_platform(root=args.root, environment=args.env, runtime=framework or args.runtime)
        port = args.port + offset
        url = f"http://{'localhost' if args.host in ('0.0.0.0', '') else args.host}:{port}/"
        app = build_app(factory, name, url=url)
        runtime = factory.runtime_name(factory.store.load(name))
        print(f"  {name:20} {runtime:10} {url}   (tarjeta: {url}.well-known/agent-card.json)")
        agents, delegates = factory.participants(name)
        participants[0].update(agents)
        participants[1].update(delegates)
        config = uvicorn.Config(app, host=args.host, port=port, log_level="warning")
        servers.append(uvicorn.Server(config))

    if args.verbose:
        from agent_core.telemetry import enable_narration

        enable_narration(agents=participants[0], delegates=participants[1])
    print("\nEsperando peticiones A2A. Ctrl+C para parar.\n", flush=True)

    async def _serve_all() -> None:
        await asyncio.gather(*(server.serve() for server in servers))

    try:
        asyncio.run(_serve_all())
    except KeyboardInterrupt:
        pass
    return 0


def cmd_card(args: argparse.Namespace) -> int:
    from .client import fetch_card

    print(json.dumps(fetch_card(args.url), indent=2, ensure_ascii=False))
    return 0


def cmd_send(args: argparse.Namespace) -> int:
    from .client import A2AError, send

    try:
        print(send(args.url, args.message))
    except A2AError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0
