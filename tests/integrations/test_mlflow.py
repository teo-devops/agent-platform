"""agent-mlflow contra un MLflow en proceso (SQLite temporal). Sin red y sin modelo."""

from __future__ import annotations

import pytest

mlflow = pytest.importorskip("mlflow")

from agent_core.evals.engine import CaseResult, SuiteResult  # noqa: E402
from agent_core.evals.schemas import EvalCase, EvalSuite  # noqa: E402
from agent_core.telemetry import prompt_hash  # noqa: E402


@pytest.fixture(scope="module")
def tracking(tmp_path_factory):
    import os

    directory = tmp_path_factory.mktemp("mlflow")
    uri = f"sqlite:///{directory / 'mlflow.db'}"
    previous, cwd = mlflow.get_tracking_uri(), os.getcwd()
    os.chdir(directory)  # SQLite stores put artefacts in ./mlruns
    mlflow.set_tracking_uri(uri)
    mlflow.set_registry_uri(uri)
    yield uri
    mlflow.set_tracking_uri(previous)
    os.chdir(cwd)


@pytest.fixture(scope="module")
def experiment(tracking):
    from agent_mlflow.common import ensure_experiment

    return ensure_experiment()


def test_the_default_experiment_is_renamed_so_its_id_is_known(experiment):
    from agent_mlflow.common import EXPERIMENT, client

    assert experiment == "0"
    assert client().get_experiment("0").name == EXPERIMENT


def test_a_prompt_version_is_created_only_when_the_text_changes(experiment, store):
    from agent_mlflow.prompts import push, version_for_hash

    manifest = store.load("code-reviewer")
    first, created = push(manifest)
    again, created_again = push(manifest)

    assert created and not created_again and first == again
    assert version_for_hash("code-reviewer", prompt_hash(manifest.spec.prompt.instruction)) == first

    manifest.spec.prompt.instruction += "\n6. Sé breve."
    second, created = push(manifest)
    assert created and int(second) == int(first) + 1


def test_each_agent_version_is_one_logged_model(experiment, factory):
    from agent_mlflow.models import register

    model_id, created = register(factory, "python-developer", experiment_id=experiment)
    same, created_again = register(factory, "python-developer", experiment_id=experiment)
    assert created and not created_again and same == model_id

    model = mlflow.get_logged_model(model_id)
    assert model.tags["agent.version"] == "0.2.0"
    assert model.params["tools"] == "code.check_syntax"
    assert model.params["skills"] == "hexagonal-architecture@^1.0"


def test_eval_results_become_a_run_attached_to_the_agent_version(experiment, factory):
    from agent_mlflow.evals import publish

    suite = EvalSuite.model_validate({
        "metadata": {"name": "coach"},
        "spec": {"target": "software-manager", "threshold": 0.5,
                 "cases": [{"id": "a", "input": "hola"}, {"id": "b", "input": "adiós"}]},
    })
    result = SuiteResult(suite=suite, judged=False)
    result.cases = [
        CaseResult(case=EvalCase(id="a", input="hola"), output="ok"),
        CaseResult(case=EvalCase(id="b", input="adiós"), output="", failures=["vacía"]),
    ]

    where = publish(result, {"factory": factory, "runtime": "adk"})
    run = mlflow.get_run(where.split()[1])

    assert run.data.metrics["pass_rate"] == 0.5
    assert run.data.tags["agent.version"] == "0.3.0"
    assert "model" in where
    model = mlflow.get_logged_model(where.split()[-1])
    assert any(m.key == "pass_rate" for m in model.metrics)


def test_traces_are_tagged_and_summarised_by_agent_version_and_framework(experiment):
    from agent_mlflow.traces import summarize, sync

    for framework in ("adk", "langgraph"):
        with mlflow.start_span("invoke_agent python-developer") as span:
            span.set_attributes({"agent.name": "python-developer", "agent.version": "0.2.0",
                                 "agent.framework": framework, "prompt.hash": "abc"})
            with mlflow.start_span("execute_tool code.check_syntax", span_type="TOOL"):
                pass

    assert sync(experiment) >= 2
    rows = {row["framework"]: row for row in summarize(experiment) if row["agent"] == "python-developer"}
    assert set(rows) >= {"adk", "langgraph"}
    assert rows["adk"]["avg_tool_calls"] == 1
