"""Del manifiesto a los CRDs de kagent: nada se escribe dos veces, nada se pierde en silencio."""

from __future__ import annotations

import copy

import pytest
import yaml
from agent_core.errors import ConfigError
from agent_kagent import Release, render
from agent_kagent.host import agent_card

RELEASE = {
    "apiVersion": "deploy.agents.platform/v1",
    "kind": "KagentRelease",
    "spec": {
        "namespace": "kagent",
        "toolServer": {"image": "reg/mcp:1", "tools": ["code.*"]},
        "host": {"image": "reg/host:1"},
        "skills": {"registry": "reg:5000"},
        "trustBundle": {"configMap": "host-ca"},
        "agents": [
            {"name": "software-manager", "mode": "declarative"},
            {"name": "code-reviewer", "mode": "declarative"},
            {"name": "python-developer", "mode": "byo", "runtime": "langgraph"},
        ],
    },
}


def _release(**changes) -> Release:
    data = copy.deepcopy(RELEASE)
    data["spec"].update(changes)
    from agent_kagent.release import _snake

    return Release.model_validate(_snake(data))


def _by_kind(documents, kind):
    return [d for d in documents if d["kind"] == kind]


def test_the_release_file_in_the_repository_loads(root):
    release = Release.load(root / "deploy/kagent/release.yaml")
    assert {a.name for a in release.spec.agents} == {"software-manager", "code-reviewer", "python-developer"}


def test_declarative_agent_is_derived_from_its_manifest(factory):
    rendered = render(factory, _release(), prompt_versions={"code-reviewer": "3"})
    documents = rendered.files["agent-code-reviewer.yaml"]
    manifest = factory.store.load("code-reviewer")

    (config_map,) = _by_kind(documents, "ConfigMap")
    assert config_map["data"]["instruction"] == manifest.spec.prompt.instruction
    assert config_map["metadata"]["annotations"]["agents.platform/prompt-version"] == "3"

    (model,) = _by_kind(documents, "ModelConfig")
    assert model["spec"]["model"] == manifest.spec.model.name

    (agent,) = _by_kind(documents, "Agent")
    assert agent["spec"]["type"] == "Declarative"
    tools = agent["spec"]["declarative"]["tools"]
    assert tools[0]["mcpServer"]["toolNames"] == ["code.check_syntax", "code.metrics", "code.find_smells"]
    assert agent["spec"]["skills"]["refs"] == ["reg:5000/skills/hexagonal-architecture:1.0.0"]

    env = {e["name"]: e.get("value") for e in agent["spec"]["declarative"]["deployment"]["env"]}
    assert "agent.version=0.2.0" in env["OTEL_RESOURCE_ATTRIBUTES"]
    assert "prompt.version=3" in env["OTEL_RESOURCE_ATTRIBUTES"]
    assert env["SSL_CERT_FILE"].endswith("ca-certificates.crt")


def test_the_coordinator_delegates_over_a2a_to_both_specialists(factory):
    (agent,) = [d for d in render(factory, _release()).files["agent-software-manager.yaml"] if d["kind"] == "Agent"]
    tools = agent["spec"]["declarative"]["tools"]
    assert tools == [
        {"type": "Agent", "agent": {"name": "python-developer"}},
        {"type": "Agent", "agent": {"name": "code-reviewer"}},
    ]


def test_what_kagent_cannot_enforce_is_reported(factory):
    warnings = render(factory, _release()).warnings
    assert any("guardrails" in w and "software-manager" in w for w in warnings)
    assert any("policies" in w for w in warnings)


def test_byo_agent_runs_the_platform_runtime(factory):
    (agent,) = render(factory, _release()).files["agent-python-developer.yaml"]
    deployment = agent["spec"]["byo"]["deployment"]
    env = {e["name"]: e.get("value") for e in deployment["env"]}

    assert agent["spec"]["type"] == "BYO"
    assert deployment["image"] == "reg/host:1"
    assert deployment["imagePullPolicy"] == "IfNotPresent"  # el valor por defecto
    assert env["AGENT"] == "python-developer" and env["AGENT_RUNTIME"] == "langgraph"
    assert "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT" not in env  # kagent injects it
    assert "agent.framework=langgraph" in env["OTEL_RESOURCE_ATTRIBUTES"]


def test_tool_server_publishes_exactly_the_release_globs(factory):
    documents = render(factory, _release()).files["00-tool-server.yaml"]
    (deployment,) = _by_kind(documents, "Deployment")
    (server,) = _by_kind(documents, "RemoteMCPServer")

    args = deployment["spec"]["template"]["spec"]["containers"][0]["args"]
    assert args[:2] == ["mcp", "serve"] and args[args.index("--tools") + 1] == "code.*"
    assert server["spec"]["url"] == "http://catalog-tools.kagent:8000/mcp"


def test_a_sub_agent_outside_the_release_is_an_error(factory):
    with pytest.raises(ConfigError, match="not in the release"):
        render(factory, _release(agents=[{"name": "software-manager", "mode": "declarative"}]))


def test_a_tool_the_server_does_not_publish_is_an_error(factory):
    toolServer = {"image": "reg/mcp:1", "tools": ["time.*"]}
    with pytest.raises(ConfigError, match="does not publish"):
        render(factory, _release(toolServer=toolServer))


def test_workflows_are_not_kagent_agents(factory):
    with pytest.raises(ConfigError, match="Workflow"):
        render(factory, _release(agents=[{"name": "research-and-write", "mode": "declarative"}]))


def test_byo_needs_a_runtime(factory):
    with pytest.raises(ConfigError, match="needs a runtime"):
        render(factory, _release(agents=[{"name": "python-developer", "mode": "byo"}]))


def test_written_files_are_valid_yaml_with_a_kustomization(factory, tmp_path):
    paths = render(factory, _release()).write(tmp_path)
    kustomization = yaml.safe_load((tmp_path / "kustomization.yaml").read_text())
    assert sorted(kustomization["resources"]) == sorted(p.name for p in paths if p.name != "kustomization.yaml")
    for path in paths:
        assert list(yaml.safe_load_all(path.read_text()))


def test_agent_card_describes_the_manifest(store):
    card = agent_card(store.load("python-developer"), url="http://python-developer.kagent:8080")
    assert card["name"] == "python-developer" and card["version"] == "0.2.0"
    assert card["skills"][0]["id"] == "python-developer"


def test_a_byo_coordinator_delegates_over_a2a_through_the_controller(factory):
    agents = [
        {"name": "software-manager", "mode": "byo", "runtime": "langgraph"},
        {"name": "code-reviewer", "mode": "declarative"},
        {"name": "python-developer", "mode": "byo", "runtime": "langgraph"},
    ]
    (agent,) = render(factory, _release(agents=agents)).files["agent-software-manager.yaml"]
    env = {e["name"]: e.get("value") for e in agent["spec"]["byo"]["deployment"]["env"]}

    endpoints = dict(pair.split("=", 1) for pair in env["AGENT_A2A_ENDPOINTS"].split(","))
    assert endpoints == {
        "python-developer": "http://kagent-controller.kagent:8083/api/a2a/kagent/python-developer/",
        "code-reviewer": "http://kagent-controller.kagent:8083/api/a2a/kagent/code-reviewer/",
    }


def test_a_byo_agent_without_sub_agents_gets_no_endpoints(factory):
    (agent,) = render(factory, _release()).files["agent-python-developer.yaml"]
    names = {e["name"] for e in agent["spec"]["byo"]["deployment"]["env"]}
    assert "AGENT_A2A_ENDPOINTS" not in names
