"""What building a manifest produces, whatever framework did the building.

This lives in ``agent-core`` on purpose. It is the only shape every runtime has
to agree on: an object the framework can run, the enforcement stack that travels
with it, and the manifest it came from. Nothing here knows what ``agent`` is —
an ADK ``LlmAgent``, a compiled LangGraph, a LangChain runnable — and that is
exactly the point.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class BuildResult:
    """An agent ready to run, with everything that must run around it."""

    #: The framework-native object. Opaque to the core.
    agent: Any

    #: Enforcement that travels with the agent (guardrails, permissions, audit).
    #: How it is applied is the runtime's business; that it exists is not.
    plugins: list[Any] = field(default_factory=list)

    #: The manifest this was built from.
    manifest: Any = None
