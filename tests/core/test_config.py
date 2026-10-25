"""Configuration resolution: merging, profiles, prompts and environments."""

from __future__ import annotations

import pytest
from agent_core.config import ConfigStore, deep_merge, interpolate, merge_all, render_template
from agent_core.errors import ConfigError


def test_deep_merge_merges_maps_and_replaces_lists():
    base = {"model": {"name": "a", "temperature": 0.1}, "tools": [1, 2]}
    override = {"model": {"temperature": 0.9}, "tools": [3]}
    assert deep_merge(base, override) == {"model": {"name": "a", "temperature": 0.9}, "tools": [3]}


def test_merge_all_applies_layers_left_to_right():
    assert merge_all({"a": 1}, {"a": 2, "b": 1}, {"b": 3}) == {"a": 2, "b": 3}


def test_interpolate_uses_defaults_and_env():
    env = {"SET": "value"}
    assert interpolate("${SET}", env) == "value"
    assert interpolate("${MISSING:-fallback}", env) == "fallback"
    assert interpolate({"k": ["${SET}"]}, env) == {"k": ["value"]}


def test_interpolate_fails_loudly_on_missing_variable():
    with pytest.raises(ConfigError, match="MISSING"):
        interpolate("${MISSING}", {})


def test_render_template_substitutes_prompt_variables():
    assert render_template("a {{ who }} b", {"who": "friend"}) == "a friend b"
    with pytest.raises(ConfigError, match="who"):
        render_template("{{ who }}", {})


def test_agent_inherits_profiles_from_defaults(store: ConfigStore):
    explainer = store.load_agent("tech-explainer")
    # 'balanced' is declared by the agent, and its values come from configs/models.yaml
    assert explainer.spec.model.profile == "balanced"
    assert explainer.spec.model.name == "gemini-2.5-flash"
    assert explainer.spec.model.temperature == 0.7
    # guardrails/policies were never mentioned by the agent: they come from defaults
    assert explainer.spec.policies.profile == "relaxed"  # local overlay
    assert explainer.spec.guardrails.input


def test_prompt_file_and_variables_are_resolved(store: ConfigStore):
    explainer = store.load_agent("tech-explainer")
    assert "una persona de negocio sin formación técnica" in explainer.spec.prompt.instruction
    assert "{{" not in explainer.spec.prompt.instruction


def test_environment_overlay_wins_over_the_manifest(root):
    production = ConfigStore(root, environment="production")
    release = production.load_agent("release-manager")
    assert release.spec.policies.max_tool_calls == 6
    assert release.spec.guardrails.profile == "strict"
    # the fleet-wide deny list of the production overlay reaches every agent
    assert "debug.*" in release.spec.permissions.tools.deny

    local = ConfigStore(root, environment="local")
    assert local.load_agent("release-manager").spec.guardrails.profile == "standard"


def test_unknown_names_and_environments_report_what_exists(store: ConfigStore, root):
    with pytest.raises(ConfigError, match="unknown agent"):
        store.load_agent("does-not-exist")
    with pytest.raises(ConfigError, match="unknown environment"):
        ConfigStore(root, environment="nope").defaults and ConfigStore(root, environment="nope").load_agent("tech-explainer")


def test_every_manifest_in_the_repository_validates(store: ConfigStore):
    for name in store.list_agents():
        assert store.load_agent(name).name == name
    for name in store.list_workflows():
        assert store.load_workflow(name).spec.nodes


def test_environment_defaults_do_not_override_an_explicit_agent_choice(root):
    """`agentDefaults` fill gaps; only `agents.<name>` overrides the manifest."""
    from agent_core.config import ConfigStore

    staging = ConfigStore(root, environment="staging")
    # staging defaults every agent to the 'standard' policy profile...
    assert staging.load_agent("tech-explainer").spec.policies.profile == "standard"
    # ...but the agent's own model choice survives the environment default
    assert staging.load_agent("tech-explainer").spec.model.profile == "balanced"

    production = ConfigStore(root, environment="production")
    # a targeted override is the way an environment forces a change
    assert production.load_agent("tech-explainer").spec.policies.profile == "frugal"
    assert production.load_agent("software-manager").spec.policies.profile == "standard"
    # and a single key can be overridden without replacing the whole profile
    release = production.load_agent("release-manager")
    assert (release.spec.policies.profile, release.spec.policies.max_tool_calls) == ("frugal", 6)
