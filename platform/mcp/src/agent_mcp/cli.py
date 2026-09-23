"""``agentctl mcp``: list or serve the catalogue's tools over MCP."""

from __future__ import annotations

import argparse
from typing import Any


def register(sub: Any) -> None:
    mcp = sub.add_parser("mcp", help="Serve the catalogue's tools over the Model Context Protocol")
    actions = mcp.add_subparsers(dest="mcp_command", required=True)

    listing = actions.add_parser("list", help="Show the tools that would be published")
    listing.add_argument("--tools", action="append", help="Glob of tool references (repeatable)")
    listing.set_defaults(func=cmd_list)

    serve = actions.add_parser("serve", help="Run the MCP server")
    serve.add_argument("--tools", action="append", help="Glob of tool references (repeatable)")
    serve.add_argument(
        "--transport", choices=["streamable-http", "stdio"], default="streamable-http",
        help="streamable-http for a network service (kagent), stdio for a local client (IDE)",
    )
    serve.add_argument("--host", default="127.0.0.1", help="Use 0.0.0.0 inside a container")
    serve.add_argument("--port", type=int, default=8000)
    serve.set_defaults(func=cmd_serve)


def _registry(args: argparse.Namespace):
    from agent_runtime import load_platform

    return load_platform(root=args.root, environment=args.env).registries.tools


def cmd_list(args: argparse.Namespace) -> int:
    from .server import select_tools

    registry = _registry(args)
    for name in select_tools(registry, args.tools):
        doc = (registry.get(name).__doc__ or "").strip().splitlines()
        print(f"  {name:28} {doc[0] if doc else ''}")
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    from .server import build_server, select_tools

    registry = _registry(args)
    server = build_server(registry, args.tools, host=args.host, port=args.port)
    if args.transport == "streamable-http":
        print(f"MCP en http://{args.host}:{args.port}/mcp  ·  {len(select_tools(registry, args.tools))} tools")
    server.run(transport=args.transport)
    return 0
