"""agent-mcp: the catalogue's tools, over the Model Context Protocol.

Inside this repository a tool is a Python function in ``catalog/tools/`` that
the runtimes call in-process. That is enough while every agent is built here.
The moment an agent is built somewhere else — a declarative kagent agent, an
IDE, another team's framework — the function has to travel over a protocol,
and MCP is the one the ecosystem agreed on.

Nothing is rewritten for that: the same registry the runtimes use is served
as-is. Type hints and docstring are already the schema.
"""

from .server import build_server, select_tools
from .version import __version__

__all__ = ["__version__", "build_server", "select_tools"]
