"""Each ``name@version`` of an agent as an MLflow ``LoggedModel``.

A LoggedModel is MLflow 3's unit of "a version of an AI application". Its params
record what that version is made of, so two versions can be compared in the UI
without opening a repository, and eval runs log their metrics against it. The
resolved manifest (what ``agentctl export`` publishes) is attached as artefact.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

import mlflow
import yaml
from agent_core.publish import resolve_agent
from agent_core.telemetry import prompt_hash

from .common import client
from .prompts import version_for_hash


def find(name: str, version: str, experiment_id: str) -> str | None:
    """The model id of ``name@version``, if it was registered."""
    models = mlflow.search_logged_models(
        experiment_ids=[experiment_id],
        filter_string=f"name = '{name}' AND tags.`agent.version` = '{version}'",
        output_format="list",
    )
    return models[0].model_id if models else None


def register(factory: Any, name: str, *, experiment_id: str) -> tuple[str, bool]:
    """Create the LoggedModel of the current version of ``name`` if it is missing."""
    manifest = factory.store.load(name)
    version = manifest.metadata.version
    existing = find(name, version, experiment_id)
    if existing:
        return existing, False

    spec = manifest.spec
    fingerprint = prompt_hash(spec.prompt.instruction or "")
    model = mlflow.create_external_model(
        name=name,
        model_type="agent",
        experiment_id=experiment_id,
        params={
            "framework": factory.runtime_name(manifest),
            "model": spec.model.name or "",
            "temperature": str(spec.model.temperature),
            "tools": ",".join(t.ref for t in spec.enabled_tools) or "-",
            "skills": ",".join(s.ref for s in spec.enabled_skills) or "-",
            "sub_agents": ",".join(s.ref for s in spec.enabled_sub_agents) or "-",
            "prompt.hash": fingerprint,
        },
        tags={"agent.name": name, "agent.version": version, "owner": manifest.metadata.owner or ""},
    )

    resolved = resolve_agent(manifest, factory.store)
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "manifest.yaml"
        path.write_text(yaml.safe_dump(resolved.document, sort_keys=False, allow_unicode=True), encoding="utf-8")
        client().log_model_artifacts(model.model_id, tmp)

    prompt_version = version_for_hash(name, fingerprint)
    if prompt_version:
        client().link_prompt_version_to_model(name, prompt_version, model.model_id)
    return model.model_id, True
