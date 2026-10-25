"""Inside the Langflow container: one trace from the flow to our agents.

Langflow opens an ``a2a.message.send`` span around each A2A call but sends no
``traceparent``, so each agent starts a trace of its own. This hook, loaded by
Python at startup (``PYTHONPATH``, see ``deploy/langflow/compose.otel.yaml``),
injects the current trace context into httpx requests to our agents, and only
to them.

Not ``HTTPXClientInstrumentor``: Langflow's exporter drops httpx spans on
purpose (the LLM SDKs ride on httpx and their spans carry URLs and keys), so the
agent would hang from a span that never reaches MLflow, and every LLM call would
be touched too. Here no span is created: the agent's parent is Langflow's own
``a2a.message.send``, which is exported.

``AGENT_TRACE_PROPAGATE_HOSTS``: comma-separated hosts that get the header
(default ``127.0.0.1,localhost``, where ``make a2a-up`` serves the agents).
"""

from __future__ import annotations

import os

DEFAULT_HOSTS = "127.0.0.1,localhost"


def install() -> bool:
    try:
        import httpx
        from opentelemetry import propagate
    except ImportError:
        return False
    hosts = {h.strip() for h in os.getenv("AGENT_TRACE_PROPAGATE_HOSTS", DEFAULT_HOSTS).split(",") if h.strip()}

    def inject(request: httpx.Request) -> None:
        if request.url.host in hosts and "traceparent" not in request.headers:
            propagate.inject(request.headers)

    sync_send, async_send = httpx.Client.send, httpx.AsyncClient.send

    def send(self, request, **kwargs):
        inject(request)
        return sync_send(self, request, **kwargs)

    async def asend(self, request, **kwargs):
        inject(request)
        return await async_send(self, request, **kwargs)

    httpx.Client.send, httpx.AsyncClient.send = send, asend
    return True


install()
