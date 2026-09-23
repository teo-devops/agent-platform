"""``agentctl eval --sink mlflow``: an eval suite as a run of the agent version.

One run per suite execution, attached to the ``LoggedModel`` of the exact
agent version that was evaluated. The score is logged against the model, so
the model page shows how each version did; the per-case table keeps input,
output, verdict and the trace id, and the traces are linked to the run.
"""

from __future__ import annotations

from typing import Any

import mlflow
from agent_core.telemetry import prompt_hash

from . import models
from .common import client, ensure_experiment
from .prompts import version_for_hash


def publish(result: Any, context: dict[str, Any]) -> str:
    """The eval sink. Returns where the result went, for the CLI to print."""
    factory, runtime = context["factory"], context["runtime"]
    suite = result.suite
    manifest = factory.store.load(suite.spec.target)
    experiment_id = ensure_experiment()

    model_id = None
    if manifest.kind == "Agent":
        model_id, _ = models.register(factory, manifest.name, experiment_id=experiment_id)

    fingerprint = prompt_hash(getattr(manifest.spec, "prompt", None) and manifest.spec.prompt.instruction or "")
    passed = sum(1 for case in result.cases if case.passed)
    total = len(result.cases) or 1

    with mlflow.start_run(
        experiment_id=experiment_id,
        run_name=f"eval {suite.name} · {manifest.name}@{manifest.metadata.version} · {runtime}",
    ) as run:
        mlflow.set_tags({
            "agent.kind": "eval",
            "agent.name": manifest.name,
            "agent.version": manifest.metadata.version,
            "agent.framework": runtime,
            "prompt.hash": fingerprint,
            "prompt.version": version_for_hash(manifest.name, fingerprint) or "unregistered",
            "eval.suite": suite.name,
        })
        mlflow.log_params({
            "metric": suite.spec.metric,
            "threshold": suite.spec.threshold,
            "judged": result.judged,
            "cases": len(result.cases),
        })
        metrics = {
            suite.spec.metric: result.score,
            "pass_rate": passed / total,
            "meets_threshold": float(result.meets_threshold),
        }
        mlflow.log_metrics(metrics, model_id=model_id)
        mlflow.log_table(
            {
                "case": [c.case.id for c in result.cases],
                "input": [c.case.input for c in result.cases],
                "output": [c.output for c in result.cases],
                "passed": [c.passed for c in result.cases],
                "failures": ["; ".join(c.failures) or (c.error or "") for c in result.cases],
                "judged": [", ".join(f"{k}={'sí' if v else 'no'}" for k, v in c.judged.items()) for c in result.cases],
                "trace_id": [c.trace_id or "" for c in result.cases],
            },
            artifact_file="cases.json",
        )
        trace_ids = [c.trace_id for c in result.cases if c.trace_id]
        if trace_ids:
            try:
                client().link_traces_to_run(trace_ids, run.info.run_id)
            except Exception:  # noqa: BLE001 - traces may still be in flight; the table keeps the ids
                pass
        return f"run {run.info.run_id}" + (f" · model {model_id}" if model_id else "")
