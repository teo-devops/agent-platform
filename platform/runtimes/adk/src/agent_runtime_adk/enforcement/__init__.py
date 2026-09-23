"""ADK enforcement plugins (guardrails, permissions, policy, audit).

Each one is also exported as an ``agent_platform.plugins`` entry point, so a
manifest can reference them by name in ``spec.plugins``."""

from .audit import AuditPlugin
from .guardrails import GuardrailPlugin
from .permissions import ToolPermissionPlugin
from .policy import PolicyPlugin

__all__ = ["AuditPlugin", "GuardrailPlugin", "PolicyPlugin", "ToolPermissionPlugin"]
