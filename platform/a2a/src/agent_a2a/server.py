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

import asyncio
import sys
import time
from collections import OrderedDict
from typing import Any

from agent_core.execution import stream_with_policies
from agent_core.telemetry import agent_span

#: Port range ``make a2a-up`` uses; one agent per port.
DEFAULT_PORT = 9100
#: How many answers are remembered per agent, and for how long, to recognise a retry.
DEDUP_SIZE = 256
DEDUP_TTL = 600.0


class Deduplicator:
    """Answers a repeated ``messageId`` with the answer it already produced.

    ``message/send`` is not idempotent: an agent with tools may already have
    written a file or opened a sandbox. When a caller retries with the same
    ``messageId`` (our client does, after a 502), running the agent again would
    do it all twice. The second request waits for the
    first (if it is still running) and gets the same answer. Failures are not
    remembered: a retry after an error does run again.
    """

    def __init__(self, *, size: int = DEDUP_SIZE, ttl: float = DEDUP_TTL) -> None:
        self.size = size
        self.ttl = ttl
        self._entries: OrderedDict[str, tuple[float, asyncio.Future]] = OrderedDict()

    async def run(self, key: str | None, produce: Any) -> tuple[str, bool]:
        """``(answer, repeated)``; ``produce`` is awaited only for a new key."""
        if not key:
            return await produce(), False
        self._expire()
        if key in self._entries:
            return await asyncio.shield(self._entries[key][1]), True
        future: asyncio.Future = asyncio.get_running_loop().create_future()
        self._entries[key] = (time.monotonic(), future)
        while len(self._entries) > self.size:
            self._entries.popitem(last=False)
        try:
            answer = await produce()
        except BaseException as exc:
            self._entries.pop(key, None)
            future.set_exception(exc)
            future.exception()  # retrieved: nobody else may be waiting
            raise
        future.set_result(answer)
        return answer, False

    def _expire(self) -> None:
        limit = time.monotonic() - self.ttl
        while self._entries and next(iter(self._entries.values()))[0] < limit:
            self._entries.popitem(last=False)


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

    seen = Deduplicator()

    class PlatformExecutor(AgentExecutor):
        """One A2A request -> one run of the agent -> one text message back."""

        async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
            request = context.get_user_input()
            started = time.monotonic()
            message_id = getattr(context.message, "message_id", None)
            print(f"⇠ A2A {name}: {_preview(request)}", file=log, flush=True)

            async def produce() -> str:
                with agent_span(result.manifest, runtime.name, request):
                    chunks = stream_with_policies(runtime, app, request, result.manifest)
                    return "".join([chunk async for chunk in chunks])

            try:
                answer, repeated = await seen.run(message_id, produce)
            except Exception as exc:  # noqa: BLE001 - the caller gets it as an A2A error
                print(f"✗ {name}: {type(exc).__name__}: {exc}", file=log, flush=True)
                raise ServerError(error=InternalError(message=f"{type(exc).__name__}: {exc}")) from exc
            mark = " (repetido: misma respuesta, sin ejecutar otra vez)" if repeated else ""
            print(f"⇢ {name} ({time.monotonic() - started:.1f}s){mark}: {_preview(answer)}", file=log, flush=True)
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
