"""Operational policy enforcement (call ceilings, token and dollar budget).

These limits protect the platform from runaway loops and unbounded spend. They
are counted per invocation, so a long conversation is not penalised for the
work done in earlier turns.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from agent_core.execution import cost_usd
from agent_core.telemetry import get_logger, log_event
from google.adk.models import LlmRequest, LlmResponse
from google.adk.plugins.base_plugin import BasePlugin

from ._scope import in_scope
from ._text import model_message

logger = get_logger("plugins.policy")


class PolicyPlugin(BasePlugin):
    """Caps the number of model calls, tool calls, tokens and dollars per invocation."""

    def __init__(
        self,
        *,
        max_tool_calls: int | None = None,
        max_llm_calls: int | None = None,
        max_tokens: int | None = None,
        max_usd: float | None = None,
        pricing: Any = None,
        agent: str = "",
        name: str = "policy",
    ) -> None:
        super().__init__(name=name)
        self.max_tool_calls = max_tool_calls
        self.max_llm_calls = max_llm_calls
        self.max_tokens = max_tokens
        self.max_usd = max_usd
        self.pricing = pricing
        self.agent = agent
        self._tool_calls: dict[str, int] = defaultdict(int)
        self._llm_calls: dict[str, int] = defaultdict(int)
        self._tokens: dict[str, int] = defaultdict(int)
        self._input_tokens: dict[str, int] = defaultdict(int)
        self._output_tokens: dict[str, int] = defaultdict(int)

    async def before_model_callback(
        self, *, callback_context: Any, llm_request: LlmRequest
    ) -> LlmResponse | None:
        if not in_scope(self.agent, callback_context):
            return None
        invocation = getattr(callback_context, "invocation_id", "-")

        if self.max_llm_calls is not None and self._llm_calls[invocation] >= self.max_llm_calls:
            return self._stop(invocation, "max_llm_calls", self.max_llm_calls)
        if self.max_tokens is not None and self._tokens[invocation] >= self.max_tokens:
            return self._stop(invocation, "max_tokens", self.max_tokens)
        if self.max_usd is not None:
            spent = cost_usd(self.pricing, self._input_tokens[invocation], self._output_tokens[invocation])
            if spent is not None and spent >= self.max_usd:
                return self._stop(invocation, "max_usd", self.max_usd)

        self._llm_calls[invocation] += 1
        return None

    async def after_model_callback(
        self, *, callback_context: Any, llm_response: LlmResponse
    ) -> LlmResponse | None:
        if not in_scope(self.agent, callback_context):
            return None
        usage = getattr(llm_response, "usage_metadata", None)
        if not usage:
            return None
        invocation = getattr(callback_context, "invocation_id", "-")
        total = getattr(usage, "total_token_count", None)
        if total:
            self._tokens[invocation] += int(total)
        self._input_tokens[invocation] += int(getattr(usage, "prompt_token_count", None) or 0)
        self._output_tokens[invocation] += int(getattr(usage, "candidates_token_count", None) or 0)
        return None

    async def before_tool_callback(
        self, *, tool: Any, tool_args: dict[str, Any], tool_context: Any
    ) -> dict | None:
        if not in_scope(self.agent, tool_context):
            return None
        invocation = getattr(tool_context, "invocation_id", "-")
        if self.max_tool_calls is not None and self._tool_calls[invocation] >= self.max_tool_calls:
            log_event(logger, "tool call rejected by policy", agent=self.agent,
                      invocation=invocation, limit="max_tool_calls", value=self.max_tool_calls)
            return {
                "error": (
                    f"Policy limit reached: this invocation already used its "
                    f"{self.max_tool_calls} allowed tool calls. Answer with what you have."
                )
            }
        self._tool_calls[invocation] += 1
        return None

    async def after_run_callback(self, *, invocation_context: Any) -> None:
        """Drop the counters of a finished invocation so they cannot leak."""
        invocation = getattr(invocation_context, "invocation_id", "-")
        for counter in (self._tool_calls, self._llm_calls, self._tokens,
                        self._input_tokens, self._output_tokens):
            counter.pop(invocation, None)
        return None

    def _stop(self, invocation: str, limit: str, value: float) -> LlmResponse:
        log_event(logger, "invocation stopped by policy", agent=self.agent,
                  invocation=invocation, limit=limit, value=value)
        return LlmResponse(
            content=model_message(
                f"This invocation reached the '{limit}' limit ({value}) configured for this agent."
            )
        )
