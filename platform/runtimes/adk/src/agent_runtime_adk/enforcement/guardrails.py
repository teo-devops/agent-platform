"""Guardrail enforcement as an ADK plugin.

The plugin owns *where* the checks run (before the model sees a prompt, after
it answers, before a tool executes); ``agent_core.guardrails`` owns *what* a
check means. Adding a rule is a configuration change; adding a rule *type* is a
change in agent-core, released as a new core version.
"""

from __future__ import annotations

from typing import Any, Sequence

from agent_core.guardrails import Verdict, evaluate
from agent_core.schemas import GuardrailRule
from agent_core.telemetry import get_logger, log_event
from google.adk.models import LlmRequest, LlmResponse
from google.adk.plugins.base_plugin import BasePlugin

from ._scope import in_scope
from ._text import content_text, last_text_of, model_message, replace_text

logger = get_logger("plugins.guardrails")


def _coerce(rules: Sequence[Any] | None) -> list[GuardrailRule]:
    """Accept rules as dicts (from YAML) or as already validated models."""
    return [rule if isinstance(rule, GuardrailRule) else GuardrailRule.model_validate(rule)
            for rule in (rules or [])]


class GuardrailPlugin(BasePlugin):
    """Applies input, output and tool guardrails to every invocation."""

    def __init__(
        self,
        *,
        input: Sequence[Any] | None = None,
        output: Sequence[Any] | None = None,
        tools: Sequence[Any] | None = None,
        agent: str = "",
        name: str = "guardrails",
    ) -> None:
        super().__init__(name=name)
        self.input_rules = _coerce(input)
        self.output_rules = _coerce(output)
        self.tool_rules = _coerce(tools)
        self.agent = agent

    # -- input --------------------------------------------------------------

    async def before_model_callback(
        self, *, callback_context: Any, llm_request: LlmRequest
    ) -> LlmResponse | None:
        if not self.input_rules or not in_scope(self.agent, callback_context):
            return None
        content, text = last_text_of(llm_request.contents or [], role="user")
        if not text:
            return None

        verdict = evaluate(text, self.input_rules)
        self._log(verdict, stage="input", context=callback_context)

        if verdict.blocked:
            return LlmResponse(content=model_message(verdict.text))
        if verdict.modified and content is not None:
            replace_text(content, verdict.text)
        return None

    # -- output -------------------------------------------------------------

    async def after_model_callback(
        self, *, callback_context: Any, llm_response: LlmResponse
    ) -> LlmResponse | None:
        if not self.output_rules or llm_response.content is None:
            return None
        if not in_scope(self.agent, callback_context):
            return None
        text = content_text(llm_response.content)
        if not text:
            return None

        verdict = evaluate(text, self.output_rules)
        self._log(verdict, stage="output", context=callback_context)

        if verdict.blocked:
            return LlmResponse(content=model_message(verdict.text))
        if verdict.modified:
            return LlmResponse(content=model_message(verdict.text))
        return None

    # -- tools --------------------------------------------------------------

    async def before_tool_callback(
        self, *, tool: Any, tool_args: dict[str, Any], tool_context: Any
    ) -> dict | None:
        if not self.tool_rules or not in_scope(self.agent, tool_context):
            return None
        payload = " ".join(str(value) for value in tool_args.values())
        verdict = evaluate(payload, self.tool_rules)
        if verdict.blocked:
            log_event(logger, "tool call blocked by guardrail", agent=self.agent,
                      tool=getattr(tool, "name", "?"), rule=verdict.findings[0].rule)
            return {"error": verdict.text}
        return None

    # -- internals ----------------------------------------------------------

    def _log(self, verdict: Verdict, *, stage: str, context: Any) -> None:
        for finding in verdict.findings:
            log_event(
                logger,
                f"guardrail {finding.action} at {stage}",
                agent=self.agent or getattr(context, "agent_name", ""),
                invocation=getattr(context, "invocation_id", ""),
                rule=finding.rule,
                type=finding.type,
                excerpt=finding.excerpt,
            )
