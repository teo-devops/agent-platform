"""Tool permission enforcement.

Permissions are applied twice on purpose. The builder never attaches a denied
tool, so the model cannot even see it; this plugin re-checks at call time so
that a tool reaching the agent through another path (a sub-agent, a toolset
resolved at runtime) is still subject to the same allow/deny lists.
"""

from __future__ import annotations

from typing import Any

from agent_core.schemas import AllowDeny
from agent_core.telemetry import get_logger, log_event
from google.adk.plugins.base_plugin import BasePlugin

from ._scope import in_scope

logger = get_logger("plugins.permissions")


class ToolPermissionPlugin(BasePlugin):
    """Denies tool calls that fall outside the agent's granted permissions."""

    def __init__(
        self,
        *,
        allow: list[str] | None = None,
        deny: list[str] | None = None,
        aliases: dict[str, str] | None = None,
        agent_allow: list[str] | None = None,
        agent_deny: list[str] | None = None,
        agent_aliases: dict[str, str] | None = None,
        agent: str = "",
        name: str = "permissions",
    ) -> None:
        super().__init__(name=name)
        self.tool_rules = AllowDeny(allow=allow if allow is not None else ["*"], deny=deny or [])
        self.agent_rules = AllowDeny(
            allow=agent_allow if agent_allow is not None else ["*"], deny=agent_deny or []
        )
        # Maps the name the model sees back to its platform reference. Delegated
        # sub-agents are tools to the model but are governed by `permissions.agents`.
        self.aliases = aliases or {}
        self.agent_aliases = agent_aliases or {}
        self.agent = agent

    async def before_tool_callback(
        self, *, tool: Any, tool_args: dict[str, Any], tool_context: Any
    ) -> dict | None:
        if not in_scope(self.agent, tool_context):
            return None
        tool_name = getattr(tool, "name", "")

        if tool_name in self.agent_aliases:
            ref, rules, kind = self.agent_aliases[tool_name], self.agent_rules, "agent"
        else:
            ref, rules, kind = self.aliases.get(tool_name, tool_name), self.tool_rules, "tool"

        if rules.permits(ref) or rules.permits(tool_name):
            return None

        log_event(logger, f"{kind} call denied by permissions", agent=self.agent, tool=tool_name, ref=ref)
        return {
            "error": (
                f"Permission denied: '{tool_name}' is not in the {kind} permissions granted to "
                f"this agent. Ask the platform owner to update the agent configuration."
            )
        }
