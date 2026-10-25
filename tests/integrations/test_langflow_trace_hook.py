"""El hook que corre dentro de Langflow: `traceparent` sólo hacia los agentes, y sin spans propios."""

from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path

import httpx
import pytest

pytest.importorskip("opentelemetry.sdk.trace")
from opentelemetry.sdk.trace import TracerProvider  # noqa: E402

HOOK = Path(__file__).parents[2] / "platform/integrations/langflow/container/sitecustomize.py"


@pytest.fixture
def hook(monkeypatch):
    """Load the hook; monkeypatch puts httpx's own send methods back afterwards."""
    monkeypatch.setattr(httpx.Client, "send", httpx.Client.send)
    monkeypatch.setattr(httpx.AsyncClient, "send", httpx.AsyncClient.send)
    monkeypatch.setenv("AGENT_TRACE_PROPAGATE_HOSTS", "127.0.0.1, localhost")
    spec = importlib.util.spec_from_file_location("langflow_trace_hook", HOOK)
    spec.loader.exec_module(importlib.util.module_from_spec(spec))


def _recorder():
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={})

    return seen, httpx.MockTransport(handle)


def test_the_agent_continues_the_span_of_the_call(hook):
    seen, transport = _recorder()
    tracer = TracerProvider().get_tracer("test")
    with tracer.start_as_current_span("a2a.message.send") as span, httpx.Client(transport=transport) as client:
        client.post("http://127.0.0.1:9104/", json={})
    _, trace_id, parent_id, _ = seen[0].headers["traceparent"].split("-")
    assert int(trace_id, 16) == span.get_span_context().trace_id
    assert int(parent_id, 16) == span.get_span_context().span_id  # no span of its own in between


def test_other_hosts_get_nothing(hook):
    seen, transport = _recorder()
    tracer = TracerProvider().get_tracer("test")
    with tracer.start_as_current_span("llm"), httpx.Client(transport=transport) as client:
        client.post("https://api.openai.com/v1/chat/completions", json={})
    assert "traceparent" not in seen[0].headers


def test_async_clients_too_and_nothing_without_a_trace(hook):
    seen, transport = _recorder()
    tracer = TracerProvider().get_tracer("test")

    async def call() -> None:
        async with httpx.AsyncClient(transport=transport) as client:
            await client.post("http://localhost:9106/", json={})
            with tracer.start_as_current_span("a2a.message.send"):
                await client.post("http://localhost:9106/", json={})

    asyncio.run(call())
    assert "traceparent" not in seen[0].headers
    assert "traceparent" in seen[1].headers
