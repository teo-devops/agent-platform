"""Telemetry helpers: structured logging and (optional) OpenTelemetry tracing."""

from .logging import configure, get_logger, log_event
from .narration import enable_narration
from .tracing import agent_attributes, agent_span, configure_tracing, flush, prompt_hash

__all__ = [
    "agent_attributes",
    "agent_span",
    "configure",
    "configure_tracing",
    "enable_narration",
    "flush",
    "get_logger",
    "log_event",
    "prompt_hash",
]
