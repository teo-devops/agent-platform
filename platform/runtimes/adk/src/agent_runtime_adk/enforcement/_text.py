"""Helpers to read and rewrite the text carried by ADK content objects."""

from __future__ import annotations

from typing import Any, Iterable

from google.genai import types


def content_text(content: types.Content | None) -> str:
    """Concatenate the textual parts of a content object."""
    if content is None or not content.parts:
        return ""
    return "".join(part.text for part in content.parts if getattr(part, "text", None))


def last_text_of(contents: Iterable[types.Content], role: str = "user") -> tuple[Any, str]:
    """Return the last content with the given role and its text."""
    latest, text = None, ""
    for content in contents or []:
        if content.role == role and content_text(content):
            latest, text = content, content_text(content)
    return latest, text


def replace_text(content: types.Content, new_text: str) -> None:
    """Replace the text of a content object in place, keeping non-text parts."""
    if not content.parts:
        return
    replaced = False
    for part in content.parts:
        if getattr(part, "text", None):
            part.text = new_text if not replaced else ""
            replaced = True


def model_message(text: str) -> types.Content:
    """Build a model-authored content object carrying ``text``."""
    return types.Content(role="model", parts=[types.Part.from_text(text=text)])
