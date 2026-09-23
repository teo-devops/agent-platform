"""OpenTelemetry tracing, configured from the standard ``OTEL_*`` variables.

The platform speaks OTel and nothing else. Where the spans end up — MLflow, a
collector, Jaeger — is decided by whoever sets ``OTEL_EXPORTER_OTLP_ENDPOINT``,
never by code in this repository. Without that variable this module does
nothing, so tracing costs nothing until someone asks for it.

Three things happen when it is enabled:

1. A ``TracerProvider`` with an OTLP/HTTP exporter is installed, unless the host
   process already installed one (kagent's BYO SDK does): then it is reused.
2. Every span gets the ``agent.*`` / ``prompt.*`` attributes of the resource —
   *who runs this process* — unless it already carries its own. Backends index
   span attributes far better than resource attributes, and a trace that
   crosses pods over A2A has one root but several agents: each keeps its own
   identity on its own spans. :func:`agent_span` sets *who answered* explicitly.
3. The instrumentors that runtime packages announce under
   ``agent_platform.instrumentors`` run. ADK emits spans natively; LangGraph and
   LangChain need an instrumentor, and each runtime brings its own.

``opentelemetry-sdk`` is an optional dependency (``agent-core[tracing]``).
"""

from __future__ import annotations

import hashlib
import os
from contextlib import contextmanager
from importlib.metadata import entry_points
from typing import Any, Iterator

from .logging import get_logger, log_event

logger = get_logger("telemetry.tracing")

#: Either one enables tracing; the signal-specific one wins, as in the OTel spec.
ENDPOINT_VARIABLES = ("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "OTEL_EXPORTER_OTLP_ENDPOINT")

#: Entry point group through which runtime packages contribute instrumentation.
INSTRUMENTORS_GROUP = "agent_platform.instrumentors"

#: Resource attribute prefixes that are copied onto every span.
PROMOTED_PREFIXES = ("agent.", "prompt.")

TRACER_NAME = "agent_platform"

_configured = False
_instrumented = False


def tracing_requested() -> bool:
    """Whether the environment asks for traces."""
    if os.getenv("AGENT_TRACING", "on").lower() in {"0", "off", "false", "no"}:
        return False
    return any(os.getenv(name) for name in ENDPOINT_VARIABLES)


def configure_tracing(service_name: str = "agent-platform") -> bool:
    """Install tracing once per process. Returns whether it is active."""
    global _configured
    if _configured:
        return True
    if not tracing_requested():
        return False

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError:
        logger.warning("tracing requested but opentelemetry-sdk is not installed; install agent-core[tracing]")
        return False

    provider = trace.get_tracer_provider()
    if not isinstance(provider, TracerProvider):
        # Resource.create merges OTEL_RESOURCE_ATTRIBUTES and OTEL_SERVICE_NAME.
        resource = Resource.create({"service.name": os.getenv("OTEL_SERVICE_NAME", service_name)})
        provider = TracerProvider(resource=resource)
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
        trace.set_tracer_provider(provider)

    provider.add_span_processor(_identity_processor(provider.resource.attributes))
    instrumented = ensure_instrumented()

    _configured = True
    log_event(logger, "tracing enabled", instrumentors=instrumented)
    return True


def _identity_processor(resource_attributes: Any) -> Any:
    """A processor that copies ``agent.*`` / ``prompt.*`` resource attributes onto spans.

    Built inside a function so the SDK is only imported when tracing is on.
    """
    from opentelemetry.sdk.trace import SpanProcessor

    promoted = {
        key: value for key, value in dict(resource_attributes).items() if key.startswith(PROMOTED_PREFIXES)
    }

    class IdentityProcessor(SpanProcessor):
        def on_start(self, span: Any, parent_context: Any = None) -> None:
            for key, value in promoted.items():
                if key not in (span.attributes or {}):
                    span.set_attribute(key, value)

    return IdentityProcessor()


def agent_attributes(manifest: Any, runtime: str) -> dict[str, str]:
    """The attributes that identify what answered: agent, version, framework, prompt."""
    attributes = {
        "agent.name": manifest.name,
        "agent.version": str(getattr(manifest.metadata, "version", "") or ""),
        "agent.kind": manifest.kind,
        "agent.framework": runtime,
    }
    prompt = getattr(getattr(manifest, "spec", None), "prompt", None)
    if prompt is not None and prompt.instruction:
        attributes["prompt.hash"] = prompt_hash(prompt.instruction)
    return attributes


def prompt_hash(text: str) -> str:
    """A short, stable fingerprint of a prompt's text.

    It is what links a trace to a registered prompt version without either side
    knowing about the other: the registry stores the hash, the span carries it.
    """
    return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()[:12]


@contextmanager
def agent_span(manifest: Any, runtime: str, message: str | None = None) -> Iterator[Any]:
    """A root span around one invocation, carrying :func:`agent_attributes`.

    A no-op context when tracing is off or the SDK is missing.
    """
    if not _configured:
        yield None
        return

    from opentelemetry import trace

    tracer = trace.get_tracer(TRACER_NAME)
    with tracer.start_as_current_span(f"invoke_agent {manifest.name}") as span:
        for key, value in agent_attributes(manifest, runtime).items():
            span.set_attribute(key, value)
        if message is not None:
            span.set_attribute("input.value", message)
        yield span


def flush(timeout_millis: int = 10000) -> None:
    """Export pending spans now. Call it before looking the traces up elsewhere."""
    if not _configured:
        return
    from opentelemetry import trace

    force_flush = getattr(trace.get_tracer_provider(), "force_flush", None)
    if force_flush:
        force_flush(timeout_millis)


def ensure_instrumented() -> list[str]:
    """Run the runtimes' instrumentors, once per process.

    Exporting (:func:`configure_tracing`) and narrating
    (:mod:`.narration`) both need the spans; whichever comes first pays.
    """
    global _instrumented
    if _instrumented:
        return []
    _instrumented = True
    return _run_instrumentors()


def _run_instrumentors() -> list[str]:
    done: list[str] = []
    for entry in entry_points(group=INSTRUMENTORS_GROUP):
        try:
            entry.load()()
            done.append(entry.name)
        except Exception as exc:  # noqa: BLE001 - one broken instrumentor must not stop the rest
            logger.warning("instrumentor '%s' failed: %s", entry.name, exc)
    return done


def reset_for_tests() -> None:
    """Forget that tracing was configured. Tests only."""
    global _configured, _instrumented
    _configured = False
    _instrumented = False
