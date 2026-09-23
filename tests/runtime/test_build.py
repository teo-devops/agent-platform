"""Building runnable ADK objects from the manifests in this repository."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
from agent_core.errors import BuildError


def test_every_manifest_builds(factory):
    names = [*factory.store.list_agents(), *factory.store.list_workflows()]
    assert names
    for name in names:
        assert factory.validate(name) == [], name


def test_tools_declared_in_configuration_reach_the_agent(factory):
    agent = factory.build_agent("health-advisor")
    assert agent.name == "health_advisor"
    assert sorted(tool.name for tool in agent.tools) == ["calculate_bmi", "get_advice"]
    assert agent.model == "gemini-2.5-flash"
    assert agent.generate_content_config.temperature == 0.1


def test_sub_agents_become_tools_of_the_coordinator(factory):
    result = factory.build("software-manager")
    assert sorted(tool.name for tool in result.agent.tools) == ["code_reviewer", "python_developer"]
    # the coordinator and both specialists each contribute their own plugin stack
    scopes = {plugin.agent for plugin in result.plugins if getattr(plugin, "agent", None)}
    assert {"software_manager", "python_developer", "code_reviewer"} <= scopes


def test_an_app_carries_the_plugins_of_the_whole_tree(factory):
    app = factory.build_app("software-manager")
    assert app.name == "software_manager"
    assert app.root_agent.name == "software_manager"
    assert len(app.plugins) >= 6


def test_workflows_compose_existing_agents(factory):
    result = factory.build("research-and-write")
    assert result.agent.name == "research_and_write"
    # steps are renamed to the node names, and their plugin scopes follow
    scopes = {plugin.agent for plugin in result.plugins if getattr(plugin, "agent", None)}
    assert {"research", "write"} <= scopes


def test_loop_workflow_uses_the_declared_iteration_budget(factory):
    result = factory.build("review-loop")
    assert result.agent.max_iterations == 2
    assert [child.name for child in result.agent.sub_agents] == ["implement", "review"]


def test_circular_delegation_is_reported_not_recursed(tmp_path: Path):
    from agent_runtime import load_platform

    root = tmp_path
    (root / "configs" / "environments").mkdir(parents=True)
    # With more than one runtime installed, a repository has to say which one
    # it runs on — the same thing configs/defaults.yaml does for real.
    (root / "configs" / "defaults.yaml").write_text("agentDefaults:\n  runtime: adk\n")
    (root / "configs" / "environments" / "local.yaml").write_text("{}\n")

    for name, other in (("first", "second"), ("second", "first")):
        directory = root / "catalog" / "agents" / "starter" / name
        directory.mkdir(parents=True)
        (directory / "agent.yaml").write_text(
            textwrap.dedent(
                f"""
                kind: Agent
                metadata:
                  name: {name}
                spec:
                  model:
                    name: gemini-2.5-flash
                  prompt:
                    instruction: loop
                  sub_agents:
                    - ref: {other}
                """
            ).strip()
        )

    factory = load_platform(root=root, environment="local", load_env_file=False)
    with pytest.raises(BuildError, match="circular"):
        factory.build("first")
