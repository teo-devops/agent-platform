"""Guardrails, permissions and policy on LangChain.

Same decisions as everywhere else — they come from ``agent_core.guardrails`` and
``AllowDeny``, which know nothing about any framework. What differs is the seam:
LangChain 1.x takes an ``AgentMiddleware`` with ``before_model``, ``after_model``
and ``wrap_tool_call``, which is a closer fit to ADK's plugin than LangGraph's
hooks are.

``wrap_tool_call`` is the reason tool permissions are enforced properly here:
unlike a wrapped function, it sees every tool call the agent makes, including
ones that arrive by a route the builder never saw.
"""

from __future__ import annotations

from typing import Any

from agent_core.errors import GuardrailViolation, PermissionDeniedError
from agent_core.guardrails import evaluate
from agent_core.schemas import GuardrailsSpec, PermissionSpec, PolicySpec
from agent_core.telemetry import get_logger, log_event

logger = get_logger("langchain.enforcement")


def build_middleware(
    *,
    agent: str,
    guardrails: GuardrailsSpec,
    policies: PolicySpec,
    permissions: PermissionSpec,
    aliases: dict[str, str],
) -> Any:
    """Build the middleware that enforces what a manifest declared."""
    from langchain.agents.middleware import AgentMiddleware

    class EnforcementMiddleware(AgentMiddleware):
        """Everything the manifest declared, around the model and the tools."""

        name = f"{agent}.enforcement"

        def before_model(self, state: Any, runtime: Any) -> dict[str, Any] | None:
            messages = _messages(state)
            _check_ceilings(agent, policies, messages)

            if not guardrails.input or not messages:
                return None
            verdict = evaluate(_text_of(messages[-1]), guardrails.input)
            if verdict.blocked:
                log_event(logger, "input blocked", agent=agent, rule=verdict.message)
                raise GuardrailViolation(verdict.message)
            if verdict.modified:
                log_event(logger, "input redacted", agent=agent)
                return {"messages": [_replace(messages[-1], verdict.text)]}
            return None

        def after_model(self, state: Any, runtime: Any) -> dict[str, Any] | None:
            messages = _messages(state)
            if not guardrails.output or not messages:
                return None
            verdict = evaluate(_text_of(messages[-1]), guardrails.output)
            if verdict.blocked:
                log_event(logger, "output blocked", agent=agent, rule=verdict.message)
                return {"messages": [_replace(messages[-1], verdict.message)]}
            if verdict.modified:
                return {"messages": [_replace(messages[-1], verdict.text)]}
            return None

        def wrap_tool_call(self, request: Any, handler: Any) -> Any:
            self._check_tool_call(request)
            return handler(request)

        async def awrap_tool_call(self, request: Any, handler: Any) -> Any:
            # `ainvoke` (agentctl run, the A2A server) goes through this one;
            # without it LangChain refuses every tool call on the async path.
            self._check_tool_call(request)
            return await handler(request)

        def _check_tool_call(self, request: Any) -> None:
            called = getattr(request, "tool_call", {}) or {}
            name = called.get("name", "")
            ref = aliases.get(name, name)

            if not permissions.tools.permits(ref):
                raise PermissionDeniedError(
                    f"agent '{agent}' is not allowed to call tool '{ref}'"
                )
            if guardrails.tools:
                verdict = evaluate(repr(called.get("args", {})), guardrails.tools)
                if verdict.blocked:
                    raise GuardrailViolation(verdict.message)

    return EnforcementMiddleware()


def _check_ceilings(agent: str, policies: PolicySpec, messages: list[Any]) -> None:
    """Read the ceilings off the conversation: correct per run, no counter to reset."""
    llm_calls = sum(1 for m in messages if getattr(m, "type", "") == "ai")
    tool_calls = sum(1 for m in messages if getattr(m, "type", "") == "tool")

    if policies.max_llm_calls and llm_calls >= policies.max_llm_calls:
        raise PermissionDeniedError(
            f"agent '{agent}' reached its ceiling of {policies.max_llm_calls} model calls"
        )
    if policies.max_tool_calls and tool_calls >= policies.max_tool_calls:
        raise PermissionDeniedError(
            f"agent '{agent}' reached its ceiling of {policies.max_tool_calls} tool calls"
        )


def _messages(state: Any) -> list[Any]:
    if isinstance(state, dict):
        return state.get("messages", [])
    return getattr(state, "messages", [])


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
