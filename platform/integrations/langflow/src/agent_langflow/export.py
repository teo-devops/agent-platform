"""A catalogue agent or workflow, as a Langflow flow that calls it over A2A.

Langflow is the console, not the engine (docs/control-plane.md): every step of
the flow is an ``A2A Agent`` node pointing at the agent's A2A endpoint, so what
answers is still the manifest — its framework, guardrails, permissions and
version. The flow is *generated* from the YAML, never the other way round, and
says so in its description.

Component templates are not written here: :func:`export_flow` takes them from
the running Langflow (``GET /api/v1/all``), so the generated flow always matches
the Langflow version that will run it.
"""

from __future__ import annotations

import copy
from typing import Any

from agent_core.errors import ConfigError
from agent_core.topology import START, edges

#: Where each component lives in Langflow's catalogue.
COMPONENTS = {
    "ChatInput": "input_output",
    "ChatOutput": "input_output",
    "A2AAgent": "models_and_agents",
    "CombineText": "processing",
}
#: Horizontal distance between columns of the generated canvas.
COLUMN = 420
ROW = 260


class _Flow:
    """Nodes and edges, built one at a time."""

    def __init__(self, templates: dict[str, Any]) -> None:
        self.templates = templates
        self.nodes: list[dict[str, Any]] = []
        self.edges: list[dict[str, Any]] = []
        self._ids: dict[str, int] = {}

    def node(self, kind: str, *, x: int, y: int, values: dict[str, Any] | None = None,
             label: str | None = None) -> str:
        try:
            template = copy.deepcopy(self.templates[COMPONENTS[kind]][kind])
        except KeyError:
            raise ConfigError(
                f"this Langflow has no '{kind}' component; it is needed to build the flow"
            ) from None
        self._ids[kind] = self._ids.get(kind, 0) + 1
        node_id = f"{kind}-{self._ids[kind]:03d}"
        for field, value in (values or {}).items():
            template["template"][field]["value"] = value
        if label:
            template["display_name"] = label
        self.nodes.append({
            "id": node_id,
            "type": "genericNode",
            "position": {"x": x, "y": y},
            "data": {"id": node_id, "type": kind, "node": template},
        })
        return node_id

    def connect(self, source: str, target: str, field: str) -> None:
        src = self._find(source)
        dst = self._find(target)
        output = src["data"]["node"]["outputs"][0]
        target_field = dst["data"]["node"]["template"][field]
        self.edges.append({
            "id": f"edge-{source}-{target}-{field}",
            "source": source,
            "target": target,
            "data": {
                "sourceHandle": {
                    "dataType": src["data"]["type"],
                    "id": source,
                    "name": output["name"],
                    "output_types": output.get("types") or ["Message"],
                },
                "targetHandle": {
                    "fieldName": field,
                    "id": target,
                    "inputTypes": target_field.get("input_types") or ["Message"],
                    "type": target_field.get("type", "str"),
                },
            },
        })

    def _find(self, node_id: str) -> dict[str, Any]:
        return next(n for n in self.nodes if n["id"] == node_id)


def export_flow(manifest: Any, *, templates: dict[str, Any], endpoints: dict[str, str],
                source: str, timeout: int = 300) -> dict[str, Any]:
    """The Langflow flow (``{name, description, data}``) for an agent or workflow manifest.

    Args:
        manifest: An ``AgentManifest`` or ``WorkflowManifest``, already loaded.
        templates: Langflow's component catalogue, as ``GET /api/v1/all`` returns it.
        endpoints: Agent name -> A2A URL (``a2a.endpoints`` of the environment).
        source: Path of the manifest, written into the flow's description.
        timeout: Seconds each A2A node waits for its agent.

    Raises:
        ConfigError: if a step has no A2A endpoint, or the shape cannot be drawn
            in Langflow (a loop).
    """
    flow = _Flow(templates)
    entry = flow.node("ChatInput", x=0, y=0)

    if manifest.kind == "Agent":
        pairs = [(START, manifest.name)]
        agent_of = {manifest.name: manifest.name}
    else:
        body = manifest.spec
        if body.type == "loop":
            raise ConfigError(
                f"'{manifest.name}' is a loop, and a Langflow flow has no edge back. Run it with "
                f"`agentctl run {manifest.name}`, or call it from Langflow as one agent "
                f"(`agentctl a2a serve {manifest.name}`)."
            )
        pairs = edges(body)
        agent_of = {node.name: node.agent for node in body.nodes}

    missing = sorted({a for a in agent_of.values() if a not in endpoints})
    if missing:
        raise ConfigError(
            f"no A2A endpoint for {missing}: add them to a2a.endpoints of the environment "
            f"(configs/environments/local-a2a.yaml) and serve them (make a2a-catalog)"
        )

    depth = _depths(pairs)
    rows: dict[int, int] = {}
    node_id: dict[str, str] = {}
    for step in sorted(depth, key=lambda s: (depth[s], s)):
        column = depth[step]
        row = rows[column] = rows.get(column, -1) + 1
        node_id[step] = flow.node(
            "A2AAgent", x=COLUMN * column, y=ROW * row, label=f"{step} · {agent_of[step]}",
            values={"mode": "External", "agent_url": endpoints[agent_of[step]], "timeout": timeout},
        )

    for step in node_id:
        incoming = [entry if origin == START else node_id[origin] for origin, target in pairs if target == step]
        flow.connect(_joined(flow, incoming, x=COLUMN * depth[step] - COLUMN // 2), node_id[step], "input_value")

    sinks = [node_id[s] for s in node_id if not any(origin == s for origin, _ in pairs)]
    last = COLUMN * (max(depth.values()) + 1)
    exit_ = flow.node("ChatOutput", x=last + COLUMN // 2, y=0)
    flow.connect(_joined(flow, sinks, x=last), exit_, "input_value")

    return {
        "name": manifest.name,
        "description": (
            f"{manifest.metadata.description} — Generado de {source} "
            f"(v{manifest.metadata.version}). No se edita aquí: se cambia el YAML y se vuelve a exportar."
        ),
        "data": {"nodes": flow.nodes, "edges": flow.edges, "viewport": {"x": 0, "y": 0, "zoom": 0.8}},
    }


def _joined(flow: _Flow, sources: list[str], *, x: int) -> str:
    """One node carrying every source's text: the source itself, or Combine Text two at a time."""
    current = sources[0]
    for index, other in enumerate(sources[1:]):
        combined = flow.node("CombineText", x=x, y=ROW * (index + 1), values={"delimiter": "\n\n---\n\n"})
        flow.connect(current, combined, "text1")
        flow.connect(other, combined, "text2")
        current = combined
    return current


def _depths(pairs: list[tuple[str, str]]) -> dict[str, int]:
    """Column of each step: one more than its deepest predecessor."""
    depth: dict[str, int] = {}
    pending = {target for _, target in pairs}
    for _ in range(len(pending) + 1):
        for step in list(pending):
            parents = [origin for origin, target in pairs if target == step]
            if all(p == START or p in depth for p in parents):
                depth[step] = 1 + max((depth.get(p, 0) for p in parents if p != START), default=0)
                pending.discard(step)
    if pending:
        raise ConfigError(f"the workflow has a cycle through {sorted(pending)}; it cannot be drawn as a flow")
    return depth
