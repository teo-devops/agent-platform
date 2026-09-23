"""OpenTelemetry instrumentation for LangChain-based runtimes.

ADK emits spans on its own; LangChain and LangGraph do not, so this runtime
brings an instrumentor. It is announced under ``agent_platform.instrumentors``
and only runs when tracing is enabled (see ``agent_core.telemetry.tracing``).

OpenInference is used because its span conventions are understood by the
common backends (MLflow among them) without any vendor SDK in this package.
"""

from __future__ import annotations


def instrument() -> None:
    """Instrument LangChain, if the optional ``tracing`` extra is installed."""
    try:
        from openinference.instrumentation.langchain import LangChainInstrumentor
    except ImportError:  # the extra is not installed: spans only from the platform
        return

    instrumentor = LangChainInstrumentor()
    if not instrumentor.is_instrumented_by_opentelemetry:
        instrumentor.instrument()
