"""Google ADK as a platform runtime.

Everything ADK-specific about *running* an agent lives behind this class:
wrapping a build into an ``App`` and streaming an answer out of it. The factory
calls these two methods and never learns which framework answered.
"""

from __future__ import annotations

from typing import Any, AsyncIterator

from agent_core.result import BuildResult
from google.adk.apps import App

from .runner import stream_once


class AdkRuntime:
    """The ``adk`` runtime: ``LlmAgent`` / ``Workflow`` objects inside an ``App``."""

    name = "adk"

    def app(self, result: BuildResult) -> App:
        """An ADK ``App`` carrying the plugin stack of the whole agent tree."""
        return App(
            name=result.manifest.metadata.python_name if result.manifest else "app",
            root_agent=result.agent,
            plugins=result.plugins,
        )

    def stream(self, app: Any, message: str) -> AsyncIterator[str]:
        return stream_once(app, message)
