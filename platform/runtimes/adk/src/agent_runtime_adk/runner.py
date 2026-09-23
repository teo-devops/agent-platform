"""Running a built app without writing ADK boilerplate."""

from __future__ import annotations

import uuid
from typing import AsyncIterator

from google.adk.apps import App
from google.adk.runners import InMemoryRunner
from google.genai import types

DEFAULT_USER = "default_user"


async def stream_once(
    app: App,
    message: str,
    *,
    user_id: str = DEFAULT_USER,
    session_id: str | None = None,
) -> AsyncIterator[str]:
    """Send one message to ``app`` and yield the text chunks it produces."""
    runner = InMemoryRunner(app=app)
    session_id = session_id or f"session-{uuid.uuid4().hex[:8]}"
    await runner.session_service.create_session(
        app_name=runner.app_name, user_id=user_id, session_id=session_id
    )

    content = types.Content(role="user", parts=[types.Part.from_text(text=message)])
    async for event in runner.run_async(user_id=user_id, session_id=session_id, new_message=content):
        if event.content and event.content.parts:
            for part in event.content.parts:
                if getattr(part, "text", None):
                    yield part.text
