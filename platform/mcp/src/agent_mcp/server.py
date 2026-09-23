"""Building an MCP server from the tool registry."""

from __future__ import annotations

import fnmatch
from typing import Any

from agent_core.errors import ConfigError
from agent_core.registry import Registry
from mcp.server.fastmcp import FastMCP

from .version import __version__

#: Name the server announces in the MCP handshake.
SERVER_NAME = "agent-platform-catalog"


def select_tools(registry: Registry[Any], patterns: list[str] | None = None) -> list[str]:
    """The tool references to publish, filtered by glob (``health.*``)."""
    names = sorted(registry.keys())
    if not patterns:
        return names
    selected = [name for name in names if any(fnmatch.fnmatchcase(name, p) for p in patterns)]
    if not selected:
        raise ConfigError(
            f"no tool matches {', '.join(patterns)}. Available: {', '.join(names) or 'none'}."
        )
    return selected


def build_server(
    registry: Registry[Any],
    patterns: list[str] | None = None,
    *,
    host: str = "127.0.0.1",
    port: int = 8000,
) -> FastMCP:
    """An MCP server publishing each selected tool under its platform reference.

    The reference (``health.calculate_bmi``) is kept as the MCP tool name, so a
    manifest, a trace and a kagent ``toolNames`` list all say the same thing.
    """
    server = FastMCP(
        SERVER_NAME,
        instructions=f"Tools of the agent-platform catalogue (agent-mcp {__version__}).",
        host=host,
        port=port,
        # Stateless: every request stands alone, so the server scales
        # horizontally and a restart loses nothing.
        stateless_http=True,
    )
    published = select_tools(registry, patterns)
    for name in published:
        function = registry.get(name)
        if not callable(function):
            raise ConfigError(f"tool '{name}' resolved to {type(function).__name__}, which is not callable")
        server.add_tool(function, name=name)

    @server.custom_route("/", methods=["GET"])
    async def about(request: Any) -> Any:
        """What a browser gets: `/mcp` speaks JSON-RPC and answers it with 406."""
        from starlette.responses import JSONResponse

        return JSONResponse({
            "server": SERVER_NAME,
            "version": __version__,
            "endpoint": str(request.url_for("about")).rstrip("/") + "/mcp",
            "transport": "streamable-http (JSON-RPC). Úsalo desde un cliente MCP, no desde el navegador.",
            "explore": "make mcp-inspector",
            "tools": {
                name: (registry.get(name).__doc__ or "").strip().splitlines()[0] for name in published
            },
        })

    return server
