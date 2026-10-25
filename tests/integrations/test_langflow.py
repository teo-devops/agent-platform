"""El export a Langflow: flujos generados del catálogo, con un nodo A2A por paso.

Las plantillas de componentes son una muestra real de Langflow 1.12.8
(fixtures/langflow_components.json), con el código fuente omitido.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from agent_core.errors import ConfigError

pytest.importorskip("agent_langflow")
from agent_langflow.export import export_flow  # noqa: E402

TEMPLATES = json.loads((Path(__file__).parent / "fixtures" / "langflow_components.json").read_text())
ENDPOINTS = {
    "tech-researcher": "http://127.0.0.1:9104/",
    "tech-writer": "http://127.0.0.1:9105/",
    "tech-explainer": "http://127.0.0.1:9106/",
    "python-developer": "http://127.0.0.1:9101/",
    "code-reviewer": "http://127.0.0.1:9102/",
}


def _export(store, name):
    return export_flow(store.load(name), templates=TEMPLATES, endpoints=ENDPOINTS, source=f"src/{name}")


def _kinds(flow):
    return [n["data"]["type"] for n in flow["data"]["nodes"]]


def _links(flow):
    by_id = {n["id"]: n for n in flow["data"]["nodes"]}

    def label(node_id):
        node = by_id[node_id]["data"]
        url = node["node"]["template"].get("agent_url", {}).get("value")
        return url or node["type"]

    return {(label(e["source"]), label(e["target"]), e["data"]["targetHandle"]["fieldName"])
            for e in flow["data"]["edges"]}


def test_one_agent_is_chat_in_a2a_chat_out(store):
    flow = _export(store, "tech-explainer")
    assert _kinds(flow) == ["ChatInput", "A2AAgent", "ChatOutput"]
    assert _links(flow) == {
        ("ChatInput", ENDPOINTS["tech-explainer"], "input_value"),
        (ENDPOINTS["tech-explainer"], "ChatOutput", "input_value"),
    }
    node = flow["data"]["nodes"][1]["data"]["node"]["template"]
    assert node["mode"]["value"] == "External"


def test_a_sequential_workflow_chains_the_agents(store):
    links = _links(_export(store, "tech-article"))
    assert (ENDPOINTS["tech-researcher"], ENDPOINTS["tech-writer"], "input_value") in links
    assert ("ChatInput", ENDPOINTS["tech-researcher"], "input_value") in links


def test_a_parallel_workflow_joins_its_branches_before_the_output(store):
    flow = _export(store, "tech-briefing")
    assert _kinds(flow).count("A2AAgent") == 2 and "CombineText" in _kinds(flow)
    links = _links(flow)
    assert {("ChatInput", ENDPOINTS["tech-researcher"], "input_value"),
            ("ChatInput", ENDPOINTS["tech-explainer"], "input_value"),
            ("CombineText", "ChatOutput", "input_value")} <= links


def test_a_loop_is_refused_with_a_way_out(store):
    with pytest.raises(ConfigError, match="no edge back"):
        _export(store, "review-loop")


def test_a_step_without_endpoint_says_what_to_serve(store):
    with pytest.raises(ConfigError, match=r"no A2A endpoint for \['release-manager'\]"):
        export_flow(store.load("release-manager"), templates=TEMPLATES, endpoints={}, source="x")


def test_the_flow_says_where_it_comes_from(store):
    flow = _export(store, "tech-article")
    assert "src/tech-article" in flow["description"] and "No se edita aquí" in flow["description"]


def test_edges_point_at_real_fields_of_the_templates(store):
    flow = _export(store, "tech-briefing")
    nodes = {n["id"]: n["data"]["node"] for n in flow["data"]["nodes"]}
    for edge in flow["data"]["edges"]:
        target = edge["data"]["targetHandle"]
        assert target["fieldName"] in nodes[edge["target"]]["template"]
        assert edge["data"]["sourceHandle"]["name"] in [o["name"] for o in nodes[edge["source"]]["outputs"]]
