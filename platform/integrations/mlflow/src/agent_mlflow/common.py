"""Connection, experiment and the small state files shared with ``render``."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import mlflow
from mlflow import MlflowClient

#: The experiment everything lands in. Traces arrive over OTLP with an
#: experiment *id* in a header, and the id of the Default experiment is the only
#: one known in advance ("0"), so :func:`ensure_experiment` renames it.
EXPERIMENT = os.getenv("AGENT_MLFLOW_EXPERIMENT", "agent-platform")
DEFAULT_EXPERIMENT_ID = "0"

#: Written by ``prompts push``, read by ``agentctl kagent render``.
PROMPT_VERSIONS = ".agent-platform/dist/prompt-versions.json"


def client() -> MlflowClient:
    return MlflowClient()


def ensure_experiment(name: str = EXPERIMENT) -> str:
    """Make ``name`` exist and be the active experiment. Returns its id."""
    c = client()
    existing = c.get_experiment_by_name(name)
    if existing is None:
        default = c.get_experiment(DEFAULT_EXPERIMENT_ID)
        if default is not None and default.name == "Default":
            c.rename_experiment(DEFAULT_EXPERIMENT_ID, name)
            experiment_id = DEFAULT_EXPERIMENT_ID
        else:
            experiment_id = c.create_experiment(name)
    else:
        experiment_id = existing.experiment_id
    mlflow.set_experiment(experiment_id=experiment_id)
    return experiment_id


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
