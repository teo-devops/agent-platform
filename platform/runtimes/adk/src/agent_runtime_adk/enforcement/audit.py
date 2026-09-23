"""The platform audit trail.

Every model call, tool call and error is logged with the agent name and the
invocation id, which is what makes a fleet of declaratively configured agents
debuggable after the fact.

The same plugin stamps the agent's identity (``agent.version``,
``prompt.hash``...) on ADK's ``invoke_agent`` span. It is the only place that
knows it in every host: in ``adk web`` one process serves the whole catalogue,
so the identity cannot come from the process.
"""

from __future__ import annotations

from typing import Any

from agent_core.telemetry import get_logger, log_event
from google.adk.models import LlmRequest, LlmResponse
from opentelemetry import trace
from google.adk.plugins.base_plugin import BasePlugin

from ._scope import in_scope
from ._text import content_text

logger = get_logger("plugins.audit")


class AuditPlugin(BasePlugin):
    """Emits a structured record for the lifecycle of every invocation."""

    def __init__(
        self,
        *,
        agent: str = "",
        include_payloads: bool = False,
        payload_chars: int = 200,
        name: str = "audit",
        attributes: dict[str, str] | None = None,
    ) -> None:
        super().__init__(name=name)
        self.agent = agent
        self.include_payloads = include_payloads
        self.payload_chars = payload_chars
        #: agent.* / prompt.* attributes of the manifest, for the agent's span.
        self.attributes = attributes or {}

    async def before_agent_callback(self, *, agent: Any, callback_context: Any) -> None:
        # Runs inside ADK's `invoke_agent` span, so the current span is this agent's.
        if self.attributes and getattr(agent, "name", None) == self.agent:
            trace.get_current_span().set_attributes(self.attributes)
        return None

    async def before_run_callback(self, *, invocation_context: Any) -> None:
        if not in_scope(self.agent, invocation_context):
            return None
        log_event(logger, "invocation started", agent=self.agent,
                  invocation=getattr(invocation_context, "invocation_id", "-"))
        return None

    async def before_model_callback(self, *, callback_context: Any, llm_request: LlmRequest) -> None:
        if not in_scope(self.agent, callback_context):
            return None
        log_event(logger, "model call", agent=self.agent,
                  invocation=getattr(callback_context, "invocation_id", "-"),
                  model=getattr(llm_request, "model", None),
                  turns=len(llm_request.contents or []))
        return None

    async def after_model_callback(self, *, callback_context: Any, llm_response: LlmResponse) -> None:
        if not in_scope(self.agent, callback_context):
            return None
        usage = getattr(llm_response, "usage_metadata", None)
        log_event(logger, "model response", agent=self.agent,
                  invocation=getattr(callback_context, "invocation_id", "-"),
                  tokens=getattr(usage, "total_token_count", None) if usage else None,
                  preview=self._preview(content_text(llm_response.content)))
        return None

    async def before_tool_callback(self, *, tool: Any, tool_args: dict[str, Any], tool_context: Any) -> None:
        if not in_scope(self.agent, tool_context):
            return None
        log_event(logger, "tool call", agent=self.agent,
                  invocation=getattr(tool_context, "invocation_id", "-"),
                  tool=getattr(tool, "name", "?"),
                  args=tool_args if self.include_payloads else sorted(tool_args))
        return None

    async def on_tool_error_callback(self, *, tool: Any, tool_args: dict[str, Any],
                                     tool_context: Any, error: Exception) -> None:
        log_event(logger, "tool error", agent=self.agent, tool=getattr(tool, "name", "?"),
                  error=str(error))
        return None

    def _preview(self, text: str) -> str | None:
        if not self.include_payloads or not text:
            return None
        return text[: self.payload_chars]
