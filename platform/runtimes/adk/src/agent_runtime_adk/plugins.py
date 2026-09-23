"""Assembly of the plugin stack declared by a manifest.

Order matters: audit observes first, then permissions and policy reject calls
that must not happen, then guardrails inspect what is left. Extra plugins
listed in ``spec.plugins`` run after the built-in stack.
"""

from __future__ import annotations

from typing import Any

from agent_core.registry import Registry
from agent_core.schemas import GuardrailsSpec, PermissionSpec, PluginRef, PolicySpec
from .enforcement import AuditPlugin, GuardrailPlugin, PolicyPlugin, ToolPermissionPlugin


def build_plugins(
    *,
    agent: str,
    guardrails: GuardrailsSpec,
    policies: PolicySpec,
    permissions: PermissionSpec,
    extra: list[PluginRef],
    registry: Registry[Any],
    tool_aliases: dict[str, str] | None = None,
    agent_aliases: dict[str, str] | None = None,
    audit: bool = True,
    attributes: dict[str, str] | None = None,
) -> list[Any]:
    """Build the plugin instances for one agent, in enforcement order."""
    plugins: list[Any] = []

    if audit:
        plugins.append(AuditPlugin(agent=agent, name=f"{agent}.audit", attributes=attributes))

    plugins.append(
        ToolPermissionPlugin(
            allow=permissions.tools.allow,
            deny=permissions.tools.deny,
            aliases=tool_aliases or {},
            agent_allow=permissions.agents.allow,
            agent_deny=permissions.agents.deny,
            agent_aliases=agent_aliases or {},
            agent=agent,
            name=f"{agent}.permissions",
        )
    )

    if policies.max_tool_calls or policies.max_llm_calls or policies.budget.max_tokens:
        plugins.append(
            PolicyPlugin(
                max_tool_calls=policies.max_tool_calls,
                max_llm_calls=policies.max_llm_calls,
                max_tokens=policies.budget.max_tokens,
                agent=agent,
                name=f"{agent}.policy",
            )
        )

    if not guardrails.is_empty:
        plugins.append(
            GuardrailPlugin(
                input=guardrails.input,
                output=guardrails.output,
                tools=guardrails.tools,
                agent=agent,
                name=f"{agent}.guardrails",
            )
        )

    for ref in extra:
        if not ref.enabled:
            continue
        factory = registry.get(ref.ref)
        plugins.append(factory(**{**ref.config, "agent": agent} if _accepts_agent(factory) else ref.config))

    return plugins


def _accepts_agent(factory: Any) -> bool:
    """Whether a plugin factory takes the conventional ``agent`` keyword."""
    import inspect

    try:
        return "agent" in inspect.signature(factory).parameters
    except (TypeError, ValueError):  # pragma: no cover - builtins and C callables
        return False
