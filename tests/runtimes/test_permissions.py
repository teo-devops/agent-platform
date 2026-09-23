"""Permission filtering at build time and at call time."""

from __future__ import annotations

import pytest
from agent_core.schemas import AllowDeny, PermissionSpec, ToolRef
from agent_runtime_adk.enforcement import ToolPermissionPlugin
from agent_runtime_adk.tools import build_tools


def test_deny_beats_allow():
    rules = AllowDeny(allow=["health.*"], deny=["health.get_*"])
    assert rules.permits("health.calculate_bmi")
    assert not rules.permits("health.get_advice")
    assert not rules.permits("text.word_count")


def test_denied_tools_are_never_attached_to_the_agent(registries):
    permissions = PermissionSpec(tools=AllowDeny(allow=["health.calculate_bmi"]))
    resolved = build_tools(
        [ToolRef(ref="health.calculate_bmi"), ToolRef(ref="health.get_advice")],
        registries.tools,
        permissions,
        agent="test",
    )
    assert [tool.name for tool in resolved.tools] == ["calculate_bmi"]
    assert resolved.denied == ["health.get_advice"]


def test_alias_renames_the_tool_the_model_sees(registries):
    resolved = build_tools(
        [ToolRef(ref="health.calculate_bmi", alias="bmi")], registries.tools, PermissionSpec(), agent="test"
    )
    assert resolved.tools[0].name == "bmi"
    assert resolved.aliases == {"bmi": "health.calculate_bmi"}


class _Tool:
    def __init__(self, name: str) -> None:
        self.name = name


class _Context:
    agent_name = "agent_under_test"
    invocation_id = "inv-1"


@pytest.mark.asyncio
async def test_plugin_rejects_a_tool_outside_the_granted_permissions():
    plugin = ToolPermissionPlugin(allow=["health.*"], aliases={"calculate_bmi": "health.calculate_bmi"},
                                  agent="agent_under_test")
    allowed = await plugin.before_tool_callback(
        tool=_Tool("calculate_bmi"), tool_args={}, tool_context=_Context()
    )
    assert allowed is None

    denied = await plugin.before_tool_callback(
        tool=_Tool("delete_everything"), tool_args={}, tool_context=_Context()
    )
    assert denied is not None and "Permission denied" in denied["error"]


@pytest.mark.asyncio
async def test_delegated_agents_are_governed_by_the_agents_rules():
    plugin = ToolPermissionPlugin(
        allow=[], deny=["*"],
        agent_allow=["python-developer"],
        agent_aliases={"python_developer": "python-developer", "code_reviewer": "code-reviewer"},
        agent="agent_under_test",
    )
    assert await plugin.before_tool_callback(
        tool=_Tool("python_developer"), tool_args={}, tool_context=_Context()) is None
    denied = await plugin.before_tool_callback(
        tool=_Tool("code_reviewer"), tool_args={}, tool_context=_Context())
    assert denied is not None and "agent permissions" in denied["error"]


@pytest.mark.asyncio
async def test_a_plugin_ignores_callbacks_of_other_agents():
    plugin = ToolPermissionPlugin(allow=[], deny=["*"], agent="someone_else")
    assert await plugin.before_tool_callback(
        tool=_Tool("anything"), tool_args={}, tool_context=_Context()) is None
