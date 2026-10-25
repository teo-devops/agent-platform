"""El servidor MCP publica el catálogo tal cual, sin reescribir ninguna tool."""

from __future__ import annotations

import json

import pytest
from agent_core.errors import ConfigError
from agent_mcp import build_server, select_tools
from mcp.shared.memory import create_connected_server_and_client_session


def test_every_catalog_tool_is_published(registries):
    assert select_tools(registries.tools) == sorted(registries.tools.keys())


def test_globs_narrow_what_is_published(registries):
    assert select_tools(registries.tools, ["release.*"]) == ["release.next_version", "release.parse_commits"]


def test_a_glob_that_matches_nothing_is_an_error(registries):
    with pytest.raises(ConfigError, match="no tool matches"):
        select_tools(registries.tools, ["nope.*"])


@pytest.mark.asyncio
async def test_tools_are_listed_with_their_schema_and_callable_over_mcp(registries):
    server = build_server(registries.tools, ["release.*"])

    async with create_connected_server_and_client_session(server) as client:
        listed = {tool.name: tool for tool in (await client.list_tools()).tools}
        assert set(listed) == {"release.next_version", "release.parse_commits"}

        schema = listed["release.next_version"].inputSchema
        assert set(schema["required"]) == {"current", "log"}
        assert "semantic version" in listed["release.next_version"].description

        result = await client.call_tool("release.next_version", {"current": "1.4.2", "log": "feat: x"})
        assert not result.isError
        payload = result.structuredContent or json.loads(result.content[0].text)
        assert payload.get("next", payload.get("result", {}).get("next")) == "1.5.0"


def test_the_root_describes_the_server_for_a_browser(registries):
    """`/mcp` sólo habla JSON-RPC (un navegador recibe 406); `/` explica qué hay."""
    from starlette.testclient import TestClient

    app = build_server(registries.tools, ["code.*"]).streamable_http_app()
    body = TestClient(app).get("/").json()
    assert body["endpoint"].endswith("/mcp")
    assert set(body["tools"]) == {"code.check_syntax", "code.find_smells", "code.metrics"}
