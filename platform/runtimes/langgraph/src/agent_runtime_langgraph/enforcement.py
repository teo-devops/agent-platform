"""Guardrails, permissions and policy on LangGraph.

The rules themselves are not reimplemented here: ``agent_core.guardrails`` and
``AllowDeny`` already decide what a rule means, framework-free. What this module
provides is the *wiring* — where in a LangGraph run those decisions get made.

ADK offers a plugin registered on the whole app; LangGraph offers
``pre_model_hook`` and ``post_model_hook`` on the react agent, plus whatever you
wrap a tool in. Same decisions, different seams.

One behavioural difference worth stating plainly: when an input guardrail
blocks, ADK returns the block message in place of the model's answer, while here
the run raises ``GuardrailViolation``. A LangGraph hook returns state updates and
cannot short-circuit the graph, and faking it by prompting the model to refuse
would be theatre — the call would still happen.
"""

from __future__ import annotations

from typing import Any

from agent_core.errors import GuardrailViolation, PermissionDeniedError
from agent_core.guardrails import evaluate
from agent_core.schemas import GuardrailsSpec, PermissionSpec, PolicySpec
from agent_core.telemetry import get_logger, log_event

logger = get_logger("langgraph.enforcement")


class Enforcement:
    """Everything a manifest declared, applied around the model and the tools."""

    def __init__(
        self,
        *,
        agent: str,
        guardrails: GuardrailsSpec,
        policies: PolicySpec,
        permissions: PermissionSpec,
    ) -> None:
        self.agent = agent
        self.name = f"{agent}.enforcement"
        self.guardrails = guardrails
        self.policies = policies
        self.permissions = permissions

    # -- hooks ---------------------------------------------------------------

    def pre_model(self, state: dict[str, Any]) -> dict[str, Any]:
        """Before the model sees anything: ceilings first, then input rules."""
        messages = state.get("messages", [])
        self._check_ceilings(messages)

        if not self.guardrails.input or not messages:
            return {}

        last = messages[-1]
        text = _text_of(last)
        if not text:
            return {}

        verdict = evaluate(text, self.guardrails.input)
        if verdict.blocked:
            log_event(logger, "input blocked", agent=self.agent, rule=verdict.message)
            raise GuardrailViolation(verdict.message)

        if verdict.modified:
            log_event(logger, "input redacted", agent=self.agent)
            # `llm_input_messages` changes what the model sees without
            # rewriting the conversation the user actually had.
            return {"llm_input_messages": [*messages[:-1], _replace(last, verdict.text)]}

        return {}

    def post_model(self, state: dict[str, Any]) -> dict[str, Any]:
        """After the model answers: output rules."""
        messages = state.get("messages", [])
        if not self.guardrails.output or not messages:
            return {}

        last = messages[-1]
        text = _text_of(last)
        if not text:
            return {}

        verdict = evaluate(text, self.guardrails.output)
        if verdict.blocked:
            log_event(logger, "output blocked", agent=self.agent, rule=verdict.message)
            return {"messages": [_replace(last, verdict.message)]}
        if verdict.modified:
            log_event(logger, "output redacted", agent=self.agent)
            return {"messages": [_replace(last, verdict.text)]}
        return {}

    def guard_tool(self, function: Any, ref: str) -> Any:
        """Re-check a tool at call time, whatever path it arrived by."""
        import functools

        @functools.wraps(function)
        def guarded(*args: Any, **kwargs: Any) -> Any:
            if not self.permissions.tools.permits(ref):
                raise PermissionDeniedError(
                    f"agent '{self.agent}' is not allowed to call tool '{ref}'"
                )
            if self.guardrails.tools:
                verdict = evaluate(repr(kwargs or args), self.guardrails.tools)
                if verdict.blocked:
                    raise GuardrailViolation(verdict.message)
            return function(*args, **kwargs)

        return guarded

    # -- internals -----------------------------------------------------------

    def _check_ceilings(self, messages: list[Any]) -> None:
        """Count what has happened so far instead of keeping a counter.

        Reading the ceiling off the conversation makes it correct per run for
        free: there is no instance state to reset between invocations.
        """
        llm_calls = sum(1 for m in messages if _kind(m) == "ai")
        tool_calls = sum(1 for m in messages if _kind(m) == "tool")

        if self.policies.max_llm_calls and llm_calls >= self.policies.max_llm_calls:
            raise PermissionDeniedError(
                f"agent '{self.agent}' reached its ceiling of "
                f"{self.policies.max_llm_calls} model calls"
            )
        if self.policies.max_tool_calls and tool_calls >= self.policies.max_tool_calls:
            raise PermissionDeniedError(
                f"agent '{self.agent}' reached its ceiling of "
                f"{self.policies.max_tool_calls} tool calls"
            )


def _kind(message: Any) -> str:
    return getattr(message, "type", "")


def _text_of(message: Any) -> str:
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(part.get("text", "") for part in content if isinstance(part, dict))
    return ""


def _replace(message: Any, text: str) -> Any:
    clone = message.model_copy() if hasattr(message, "model_copy") else message
    clone.content = text
    return clone
