"""Timeout, reintentos y presupuesto: lo que antes se declaraba y no se aplicaba."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from agent_core.errors import GuardrailViolation
from agent_core.execution import (
    BudgetExceeded,
    InvocationTimeout,
    check_budget,
    cost_usd,
    guarded_stream,
)
from agent_core.schemas import BudgetSpec, ModelPricing


async def _collect(stream):
    return [chunk async for chunk in stream]


def _flaky(failures: int, *, error: type[Exception] = ConnectionError, chunks=("ho", "la")):
    """Un `start` que falla `failures` veces antes de responder."""
    calls = {"n": 0}

    def start():
        async def stream():
            calls["n"] += 1
            if calls["n"] <= failures:
                raise error("transitorio")
            for chunk in chunks:
                yield chunk

        return stream()

    return start, calls


@pytest.mark.asyncio
async def test_without_limits_the_stream_passes_through():
    start, calls = _flaky(0)
    assert await _collect(guarded_stream(start)) == ["ho", "la"]
    assert calls["n"] == 1


@pytest.mark.asyncio
async def test_a_slow_invocation_is_cut_at_its_timeout():
    def start():
        async def stream():
            yield "primero"
            await asyncio.sleep(5)
            yield "nunca"

        return stream()

    with pytest.raises(InvocationTimeout, match="0.1s"):
        await _collect(guarded_stream(start, timeout_seconds=0.1, agent="lento"))


@pytest.mark.asyncio
async def test_a_transient_failure_is_retried_before_anything_is_yielded():
    start, calls = _flaky(2)
    chunks = await _collect(guarded_stream(start, retry_attempts=2, backoff=0))
    assert chunks == ["ho", "la"]
    assert calls["n"] == 3


@pytest.mark.asyncio
async def test_retries_run_out():
    start, calls = _flaky(5)
    with pytest.raises(ConnectionError):
        await _collect(guarded_stream(start, retry_attempts=1, backoff=0))
    assert calls["n"] == 2


@pytest.mark.asyncio
async def test_a_guardrail_is_a_verdict_and_is_never_retried():
    start, calls = _flaky(1, error=GuardrailViolation)
    with pytest.raises(GuardrailViolation):
        await _collect(guarded_stream(start, retry_attempts=3, backoff=0))
    assert calls["n"] == 1


@pytest.mark.asyncio
async def test_nothing_is_retried_once_part_of_the_answer_is_out():
    calls = {"n": 0}

    def start():
        async def stream():
            calls["n"] += 1
            yield "media respuesta"
            raise ConnectionError("se cortó")

        return stream()

    seen = []
    with pytest.raises(ConnectionError):
        async for chunk in guarded_stream(start, retry_attempts=3, backoff=0):
            seen.append(chunk)
    assert seen == ["media respuesta"]
    assert calls["n"] == 1


@pytest.mark.asyncio
async def test_an_empty_answer_is_retried():
    calls = {"n": 0}

    def start():
        async def stream():
            calls["n"] += 1
            if calls["n"] == 1:
                yield "  "  # sólo espacios: no es una respuesta
                return
            yield "ahora sí"

        return stream()

    chunks = await _collect(guarded_stream(start, retry_attempts=1, backoff=0))
    assert chunks[-1] == "ahora sí"
    assert calls["n"] == 2


@pytest.mark.asyncio
async def test_without_retries_an_empty_answer_is_returned_as_is():
    start, calls = _flaky(0, chunks=())
    assert await _collect(guarded_stream(start, retry_attempts=0)) == []
    assert calls["n"] == 1


def test_cost_is_dollars_per_million_tokens():
    pricing = ModelPricing(input_per_mtok=0.30, output_per_mtok=2.50)
    assert cost_usd(pricing, 1_000_000, 0) == pytest.approx(0.30)
    assert cost_usd(pricing, 0, 400_000) == pytest.approx(1.0)
    assert cost_usd(None, 10, 10) is None


def test_the_budget_cuts_by_tokens_and_by_dollars():
    pricing = ModelPricing(input_per_mtok=1.0, output_per_mtok=1.0)
    check_budget("a", BudgetSpec(max_tokens=100), pricing, 40, 40)  # bajo el techo

    with pytest.raises(BudgetExceeded, match="100 tokens"):
        check_budget("a", BudgetSpec(max_tokens=100), pricing, 60, 40)
    with pytest.raises(BudgetExceeded, match=r"\$0.5"):
        check_budget("a", BudgetSpec(max_usd=0.5), pricing, 300_000, 200_000)


def test_a_dollar_budget_without_a_price_cannot_count():
    check_budget("a", BudgetSpec(max_usd=0.0001), None, 10**9, 10**9)


def test_every_model_profile_has_a_price(store):
    """Sin precio, `budget.max_usd` no corta nunca: que no se olvide al añadir un perfil."""
    missing = [name for name, profile in store.profiles("models").items() if "pricing" not in profile]
    assert not missing, f"perfiles sin pricing en configs/models.yaml: {missing}"


@pytest.mark.asyncio
async def test_adk_stops_an_invocation_that_spent_its_dollars():
    from agent_runtime_adk.enforcement import PolicyPlugin

    plugin = PolicyPlugin(max_usd=0.001, pricing=ModelPricing(input_per_mtok=1.0, output_per_mtok=1.0),
                          agent="caro")
    context = SimpleNamespace(agent_name="caro", invocation_id="inv-1")
    usage = SimpleNamespace(total_token_count=2000, prompt_token_count=1000, candidates_token_count=1000)

    assert await plugin.before_model_callback(callback_context=context, llm_request=None) is None
    await plugin.after_model_callback(callback_context=context,
                                      llm_response=SimpleNamespace(usage_metadata=usage))
    stopped = await plugin.before_model_callback(callback_context=context, llm_request=None)
    assert stopped is not None
    assert "max_usd" in stopped.content.parts[0].text


def test_langgraph_reads_the_spend_off_the_conversation():
    from agent_core.schemas import GuardrailsSpec, PermissionSpec, PolicySpec
    from agent_runtime_langgraph.enforcement import Enforcement

    enforcement = Enforcement(
        agent="caro",
        guardrails=GuardrailsSpec(),
        policies=PolicySpec(budget=BudgetSpec(max_tokens=500)),
        permissions=PermissionSpec(),
    )
    answered = SimpleNamespace(type="ai", content="ok",
                               usage_metadata={"input_tokens": 400, "output_tokens": 200})
    with pytest.raises(BudgetExceeded):
        enforcement.pre_model({"messages": [answered]})
