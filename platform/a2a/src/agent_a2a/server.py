"""Any catalogue agent, served over A2A.

The same build ``agentctl run`` uses — manifest, framework, guardrails,
permissions — behind an A2A JSON-RPC endpoint and an agent card. Nothing here is
framework-specific: the executor goes through the runtime's ``stream``, so an
agent on ADK, LangGraph or LangChain is served the same way. That is what lets
a coordinator on one framework delegate to a developer on another.

kagent's BYO host (``agentctl kagent host``) does the same job inside a pod
with kagent's SDK; this one needs no cluster.
"""

from __future__ import annotations

import sys
import time
from typing import Any

from agent_core.telemetry import agent_span

#: Port range ``make a2a-up`` uses; one agent per port.
DEFAULT_PORT = 9100


def agent_card(manifest: Any, *, url: str, runtime: str) -> Any:
    """The card other agents read before delegating: who this is and what it does."""
    from a2a.types import AgentCapabilities, AgentCard, AgentSkill

    description = manifest.metadata.description or manifest.name
    return AgentCard(
        name=manifest.name,
        description=description,
        url=url,
        version=str(manifest.metadata.version),
        capabilities=AgentCapabilities(streaming=False),
        default_input_modes=["text"],
        default_output_modes=["text"],
        skills=[
            AgentSkill(
                id=manifest.name,
                name=manifest.name,
                description=description,
                tags=[*manifest.metadata.tags, f"framework:{runtime}"],
            )
        ],
    )


def build_app(factory: Any, name: str, *, url: str, log: Any = sys.stderr) -> Any:
    """A Starlette app answering A2A for ``name``, built by ``factory``."""
    from a2a.server.agent_execution import AgentExecutor, RequestContext
    from a2a.server.apps import A2AStarletteApplication
    from a2a.server.events import EventQueue
    from a2a.server.request_handlers import DefaultRequestHandler
    from a2a.server.tasks import InMemoryTaskStore
    from a2a.types import InternalError, UnsupportedOperationError
    from a2a.utils import new_agent_text_message
    from a2a.utils.errors import ServerError

    result = factory.build(name)
    runtime = factory.runtime(factory.runtime_name(result.manifest))
    app = runtime.app(result)

    class PlatformExecutor(AgentExecutor):
        """One A2A request -> one run of the agent -> one text message back."""

        async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
            request = context.get_user_input()
            started = time.monotonic()
            print(f"⇠ A2A {name}: {_preview(request)}", file=log, flush=True)
            try:
                with agent_span(result.manifest, runtime.name, request):
                    answer = "".join([chunk async for chunk in runtime.stream(app, request)])
            except Exception as exc:  # noqa: BLE001 - the caller gets it as an A2A error
                print(f"✗ {name}: {type(exc).__name__}: {exc}", file=log, flush=True)
                raise ServerError(error=InternalError(message=f"{type(exc).__name__}: {exc}")) from exc
            print(f"⇢ {name} ({time.monotonic() - started:.1f}s): {_preview(answer)}", file=log, flush=True)
            await event_queue.enqueue_event(new_agent_text_message(answer, context.context_id, context.task_id))

        async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
            raise ServerError(error=UnsupportedOperationError())

    handler = DefaultRequestHandler(agent_executor=PlatformExecutor(), task_store=InMemoryTaskStore())
    card = agent_card(result.manifest, url=url, runtime=runtime.name)
    return _TraceContext(A2AStarletteApplication(agent_card=card, http_handler=handler).build())


class _TraceContext:
    """Continue the caller's trace: read ``traceparent`` before the agent runs.

    ASGI middleware rather than framework instrumentation, so a delegation that
    crosses processes stays one trace without another dependency. The tasks the
    request handler spawns copy the context, so the agent's spans inherit it.
    """

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        try:
            from opentelemetry import context, propagate
        except ImportError:  # pragma: no cover - tracing is optional
            await self.app(scope, receive, send)
            return
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        headers = {k.decode("latin-1"): v.decode("latin-1") for k, v in scope.get("headers", [])}
        token = context.attach(propagate.extract(headers))
        try:
            await self.app(scope, receive, send)
        finally:
            context.detach(token)


def _preview(text: str, limit: int = 100) -> str:
    flat = " ".join(str(text).split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"
