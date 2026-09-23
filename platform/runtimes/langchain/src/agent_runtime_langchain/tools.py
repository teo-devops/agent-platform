"""Turning registered functions into LangChain tools.

The tools themselves are plain Python functions with type hints and a docstring,
loaded from ``catalog/tools/`` and shared by every runtime. Nothing in them
knows about LangChain — the wrapping happens here, and ADK does the equivalent
in its own package.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agent_core.registry import Registry
from agent_core.schemas import PermissionSpec, ToolRef
from agent_core.telemetry import get_logger, log_event

logger = get_logger("langchain.tools")


@dataclass
class ResolvedTools:
    tools: list[Any] = field(default_factory=list)
    aliases: dict[str, str] = field(default_factory=dict)
    denied: list[str] = field(default_factory=list)


def build_tools(
    refs: list[ToolRef],
    registry: Registry[Any],
    permissions: PermissionSpec,
    *,
    agent: str = "",
) -> ResolvedTools:
    """Resolve tool references, dropping anything permissions do not allow.

    A denied tool is never attached, so the model does not even see it. The
    permission is checked again at call time — see :mod:`.enforcement`.
    """
    from langchain_core.tools import StructuredTool

    resolved = ResolvedTools()

    for ref in refs:
        if not permissions.tools.permits(ref.ref):
            resolved.denied.append(ref.ref)
            continue

        function = registry.get(ref.ref)
        name = ref.alias or ref.ref.replace(".", "_")
        resolved.tools.append(
            StructuredTool.from_function(func=function, name=name, description=function.__doc__)
        )
        resolved.aliases[name] = ref.ref

    if resolved.denied:
        log_event(logger, "tools denied at build time", agent=agent, tools=resolved.denied)

    return resolved
