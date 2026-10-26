"""``agentctl a2a``: serve catalogue agents over A2A, read a card, send a message.

Where each agent listens is written once, in ``configs/environments/local-a2a.yaml``:
``serve`` takes its ports from there and ``ping`` checks those same URLs, so the
coordinator can never end up calling the wrong agent because a list was reordered.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from typing import Any
from urllib.parse import urlparse

from .server import DEFAULT_PORT

#: The environment that says where each agent listens when served locally.
ENDPOINTS_ENV = "local-a2a"


def register(sub: Any) -> None:
    a2a = sub.add_parser("a2a", help="Agents over A2A: serve them, read their card, talk to them")
    actions = a2a.add_subparsers(dest="a2a_command", required=True)

    serve = actions.add_parser(
        "serve",
        help="Serve one or more agents over A2A, one port each",
        description="Each agent is `name` or `name:framework` (python-developer:langgraph). "
                    f"Each one listens on the port its URL has in configs/environments/{ENDPOINTS_ENV}.yaml; "
                    "with --port, on consecutive ports from there instead.",
    )
    serve.add_argument("agents", nargs="+", metavar="agent[:framework]")
    serve.add_argument(
        "--port", type=int,
        help=f"First of consecutive ports, ignoring {ENDPOINTS_ENV}.yaml (e.g. {DEFAULT_PORT + 1})",
    )
    serve.add_argument(
        "--endpoints-env", default=ENDPOINTS_ENV,
        help=f"The environment whose a2a.endpoints give the ports (default: {ENDPOINTS_ENV})",
    )
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

    ping = actions.add_parser(
        "ping",
        help=f"Which agents of {ENDPOINTS_ENV}.yaml answer, with their card (exit 1 if any does not)",
    )
    ping.add_argument("agents", nargs="*", metavar="agent[:framework]", help="Default: every declared endpoint")
    ping.add_argument("--wait", type=float, default=0, metavar="SECONDS", help="Keep trying this long")
    ping.add_argument("-q", "--quiet", action="store_true", help="Print nothing; just the exit code")
    ping.add_argument(
        "--missing", action="store_true",
        help="Print only the agents (as given, with their :framework) that do not answer",
    )
    ping.add_argument("--endpoints-env", default=ENDPOINTS_ENV)
    ping.set_defaults(func=cmd_ping)


def endpoints(root: Any, environment: str) -> dict[str, str]:
    """Agent -> A2A URL, as the environment declares them."""
    from agent_core.config import ConfigStore
    from agent_runtime.context import find_root

    return ConfigStore(root or find_root(), environment=environment).remote_agents


def serve_ports(names: list[str], declared: dict[str, str], first: int | None) -> list[int]:
    """The port of each agent: its declared URL's, or consecutive from ``first``."""
    from agent_core.errors import ConfigError

    if first is not None:
        return [first + offset for offset in range(len(names))]
    ports = []
    for name in names:
        url = declared.get(name)
        port = urlparse(url).port if url else None
        if port is None:
            raise ConfigError(
                f"'{name}' no tiene URL con puerto en a2a.endpoints de {ENDPOINTS_ENV}.yaml: "
                f"añádela ahí (es lo que lee el coordinador) o usa --port"
            )
        ports.append(port)
    return ports


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn
    from agent_runtime import load_platform

    from .server import build_app

    from agent_core.errors import PlatformError

    names = [spec.partition(":")[0] for spec in args.agents]
    try:
        ports = serve_ports(names, endpoints(args.root, args.endpoints_env), args.port)
    except PlatformError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    servers, participants = [], ({}, {})
    for spec, port in zip(args.agents, ports):
        name, _, framework = spec.partition(":")
        factory = load_platform(root=args.root, environment=args.env, runtime=framework or args.runtime)
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


def cmd_ping(args: argparse.Namespace) -> int:
    from .client import A2AError, fetch_card

    declared = endpoints(args.root, args.endpoints_env)
    names = [spec.partition(":")[0] for spec in args.agents] or list(declared)
    unknown = [name for name in names if name not in declared]
    if unknown:
        print(f"error: sin URL en {args.endpoints_env}.yaml: {', '.join(unknown)}", file=sys.stderr)
        return 2

    deadline = time.monotonic() + args.wait
    cards: dict[str, dict | None] = {}
    while True:
        for name in names:
            if cards.get(name) is None:
                try:
                    cards[name] = fetch_card(declared[name], timeout=2)
                except A2AError:
                    cards[name] = None
        if all(cards.values()) or time.monotonic() >= deadline:
            break
        time.sleep(1)

    if args.missing:
        specs = args.agents or names
        print(" ".join(spec for spec in specs if not cards[spec.partition(":")[0]]))
    elif not args.quiet:
        for name in names:
            card = cards[name]
            mark, note = ("✓", (card.get("description") or "")[:60]) if card else ("✗", "no responde")
            print(f"  {mark} {name:<20} {declared[name]:<26} {note}")
        up = sum(1 for card in cards.values() if card)
        print(f"\n  {up}/{len(names)} responden" + ("" if up == len(names) else "  ·  make a2a-up para levantarlos"))
    return 0 if all(cards.values()) else 1
