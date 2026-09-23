"""Model resolution for the LangChain runtime.

The manifest names generation settings in provider-neutral words. Not every
provider has every knob — ``top_k`` does not exist in OpenAI and ``stop`` is
what others call ``stop_sequences`` — so anything this provider cannot honour is
dropped with a warning instead of silently ignored or crashed on.

Yes, this is nearly the same file as the langgraph runtime's. That is
deliberate: each runtime package must stand on its own, so that installing
``agent-runtime-langchain`` does not drag LangGraph in behind it.
"""

from __future__ import annotations

import os
from typing import Any

from agent_core.errors import BuildError
from agent_core.schemas import ModelSpec
from agent_core.telemetry import get_logger, log_event

logger = get_logger("langchain.model")

DEFAULT_MODEL = "gemini-2.5-flash"

#: Where Gemini's key is read from, in the order google-genai checks them.
API_KEY_VARIABLES = ("GOOGLE_API_KEY", "GEMINI_API_KEY")
#: Stand-in used when there is no key, so a graph can still be built and shown.
MISSING_KEY = "missing-GOOGLE_API_KEY"


def resolve_model(spec: ModelSpec) -> Any:
    """Build the chat model the manifest asks for."""
    try:
        from langchain_google_genai import ChatGoogleGenerativeAI
    except ImportError as exc:  # pragma: no cover - declared dependency
        raise BuildError(
            "langchain-google-genai is not installed; the langgraph runtime needs it"
        ) from exc

    settings: dict[str, Any] = {}
    if spec.temperature is not None:
        settings["temperature"] = spec.temperature
    if spec.top_p is not None:
        settings["top_p"] = spec.top_p
    if spec.top_k is not None:
        settings["top_k"] = spec.top_k
    if spec.max_output_tokens is not None:
        settings["max_output_tokens"] = spec.max_output_tokens

    if spec.stop_sequences:
        # Gemini calls them stop sequences too, but the LangChain binding takes
        # them per call rather than per model, so they are not applied here.
        log_event(
            logger,
            "stop_sequences ignored",
            reason="not a constructor argument of ChatGoogleGenerativeAI",
            count=len(spec.stop_sequences),
        )

    # ChatGoogleGenerativeAI insists on a key when it is *constructed*, not when
    # it is called. Without this, a missing key breaks everything that only
    # builds the graph — `agentctl validate`, and LangGraph Studio drawing it.
    # The key is only needed to talk to the model, and that call still fails,
    # with Google's API_KEY_INVALID.
    if not any(os.getenv(name) for name in API_KEY_VARIABLES):
        log_event(logger, "no GOOGLE_API_KEY: the graph builds, calls to the model will fail",
                  model=spec.name or DEFAULT_MODEL)
        settings["google_api_key"] = MISSING_KEY

    return ChatGoogleGenerativeAI(model=spec.name or DEFAULT_MODEL, **settings)
