"""Every agent's prompt in MLflow's Prompt Registry, versioned by content.

A version is created only when the text changes: pushing twice is a no-op, and
the version number that ``render`` stamps on a deployment always means exactly
one text. The link back from a trace is the prompt hash, which the platform
puts on every span and the registry keeps as a tag.
"""

from __future__ import annotations

from typing import Any

import mlflow
from agent_core.telemetry import prompt_hash

from .common import client

HASH_TAG = "prompt.hash"


def push(manifest: Any) -> tuple[str, bool]:
    """Register ``manifest``'s prompt if it changed. Returns ``(version, created)``."""
    text = manifest.spec.prompt.instruction
    fingerprint = prompt_hash(text)

    found = version_for_hash(manifest.name, fingerprint)
    if found:
        return found, False

    registered = mlflow.genai.register_prompt(
        name=manifest.name,
        template=text,
        commit_message=f"{manifest.name}@{manifest.metadata.version}",
        tags={
            HASH_TAG: fingerprint,
            "agent.name": manifest.name,
            "agent.version": manifest.metadata.version,
        },
    )
    return str(registered.version), True


def version_for_hash(name: str, fingerprint: str) -> str | None:
    """The registered version whose text has this hash, if any."""
    c = client()
    try:
        versions = list(c.search_prompt_versions(name))
    except Exception:  # noqa: BLE001 - the prompt does not exist yet
        return None
    for version in versions:
        tags = version.tags or (c.get_prompt_version(name, version.version).tags or {})
        if tags.get(HASH_TAG) == fingerprint:
            return str(version.version)
    return None
