"""Agent scoping for plugins.

ADK plugins are registered on the whole ``App``, so their callbacks fire for
every agent in the tree. The platform builds one plugin instance per agent
manifest, and each instance ignores callbacks that belong to a different agent.
That is what lets a sub-agent carry guardrails and permissions of its own while
still using ADK's single, app-level plugin manager.
"""

from __future__ import annotations

from typing import Any


def in_scope(agent: str, context: Any) -> bool:
    """Whether a callback for ``context`` belongs to the agent this plugin guards.

    An empty ``agent`` means "no scoping": the plugin applies fleet-wide.
    """
    if not agent:
        return True
    name = getattr(context, "agent_name", None)
    if name is None:
        current = getattr(context, "agent", None)
        name = getattr(current, "name", None)
    return name is None or name == agent
