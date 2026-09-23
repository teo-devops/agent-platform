"""Resolution of ``spec.tools`` into ADK tool objects.

Permissions are applied here as a *filter*: a tool the environment denies is
never attached, so an environment overlay can restrict a fleet of agents
without editing any agent manifest. The permissions plugin repeats the check at
call time.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agent_core.errors import ConfigError
from agent_core.registry import Registry
from agent_core.schemas import PermissionSpec, ToolRef
from agent_core.telemetry import get_logger, log_event
from google.adk.tools import FunctionTool

logger = get_logger("runtime.tools")


@dataclass
class ResolvedTools:
    """Tools attached to an agent, plus the bookkeeping the plugins need."""

    tools: list[Any] = field(default_factory=list)
    #: tool name as the model sees it -> platform reference
    aliases: dict[str, str] = field(default_factory=dict)
    #: references skipped because permissions denied them
    denied: list[str] = field(default_factory=list)


def build_tools(
    refs: list[ToolRef],
    registry: Registry[Any],
    permissions: PermissionSpec,
    *,
    agent: str = "",
) -> ResolvedTools:
    """Look up every tool reference and wrap it for ADK."""
    resolved = ResolvedTools()

    for ref in refs:
        if not permissions.tools.permits(ref.ref):
            resolved.denied.append(ref.ref)
            log_event(logger, "tool not attached: denied by permissions", agent=agent, tool=ref.ref)
            continue

        function = registry.get(ref.ref)
        if not callable(function):
            raise ConfigError(f"tool '{ref.ref}' resolved to {type(function).__name__}, which is not callable")

        tool = FunctionTool(func=function)
        if ref.alias:
            tool.name = ref.alias
        resolved.tools.append(tool)
        resolved.aliases[tool.name] = ref.ref

    return resolved
