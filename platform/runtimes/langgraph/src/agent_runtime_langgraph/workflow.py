"""``kind: Workflow`` on LangGraph.

This is where the two models line up best. The platform describes a pipeline as
nodes and edges; ``StateGraph`` *is* nodes and edges. The shape is worked out
framework-free in :mod:`agent_core.topology`, and this only maps those names
onto graph nodes.

The dataflow the manifest declares in ``with`` is honoured literally here:
``{{ inputs.x }}`` reads the workflow input, ``{{ steps.y.output }}`` reads what
step ``y`` produced. That is the same wiring the orchestrator sees when the
workflow is published — so what runs locally and what runs on the cluster are
reading the same instructions.
"""

from __future__ import annotations

import re
from typing import Annotated, Any, TypedDict

from agent_core.errors import BuildError
from agent_core.result import BuildResult
from agent_core.schemas import WorkflowManifest
from agent_core.schemas.workflow import START as START_TOKEN
from agent_core.telemetry import get_logger, log_event
from agent_core.topology import edges as topology_edges

logger = get_logger("langgraph.workflow")

_INPUT_REF = re.compile(r"{{\s*inputs\.([a-zA-Z0-9_]+)\s*}}")
_STEP_REF = re.compile(r"{{\s*steps\.([a-zA-Z0-9_-]+)\.output\s*}}")


def _merge(left: dict[str, str], right: dict[str, str]) -> dict[str, str]:
    """Reducer for ``outputs``: parallel steps write into the same dict."""
    return {**left, **right}


class FlowState(TypedDict, total=False):
    inputs: dict[str, str]
    outputs: Annotated[dict[str, str], _merge]
    iteration: int


class WorkflowBuilder:
    """Composes existing agents into a deterministic graph."""

    kind = "Workflow"
    runtime = "langgraph"

    def build(self, manifest: WorkflowManifest, factory: Any) -> BuildResult:
        from langgraph.graph import END, START, StateGraph

        body = manifest.spec
        graph = StateGraph(FlowState)
        plugins: list[Any] = []

        for node in body.nodes:
            if not body.permissions.agents.permits(node.agent):
                raise BuildError(
                    f"workflow '{manifest.name}' uses agent '{node.agent}', "
                    f"which its permissions.agents rules do not allow"
                )
            child = factory.build(node.agent)
            plugins.extend(child.plugins)
            graph.add_node(node.name, _step(node, child))

        names = [node.name for node in body.nodes]
        pairs = topology_edges(body)
        for origin, target in pairs:
            graph.add_edge(START if origin == START_TOKEN else origin, target)

        terminal = [name for name in names if not any(origin == name for origin, _ in pairs)]

        if body.type == "loop":
            # Repetition is not an edge in the manifest, and it is not one here
            # either: it is a decision taken after the last step about whether to
            # go round again.
            limit = body.max_iterations or 3
            first, last = names[0], names[-1]

            def again(state: FlowState) -> str:
                return first if state.get("iteration", 1) < limit else END

            graph.add_conditional_edges(last, again, {first: first, END: END})
        else:
            for name in terminal:
                graph.add_edge(name, END)

        log_event(
            logger,
            "workflow built",
            workflow=manifest.name,
            runtime="langgraph",
            type=body.type,
            steps=names,
        )
        return BuildResult(agent=graph.compile(name=manifest.metadata.python_name),
                           plugins=plugins, manifest=manifest)


def _step(node: Any, child: BuildResult) -> Any:
    """One graph node: read what the manifest says, run the agent, write it back."""

    def run(state: FlowState) -> dict[str, Any]:
        request = _request(node, state)
        answer = child.agent.invoke({"messages": [{"role": "user", "content": request}]})
        messages = answer.get("messages", [])
        text = messages[-1].text if messages else ""
        return {
            "outputs": {node.name: text},
            "iteration": state.get("iteration", 0) + 1,
        }

    return run


def _request(node: Any, state: FlowState) -> str:
    """Resolve ``with`` against the state; fall back to the workflow input."""
    inputs = state.get("inputs", {})
    outputs = state.get("outputs", {})

    if not node.with_:
        if node.needs:
            return "\n\n".join(outputs.get(dependency, "") for dependency in node.needs)
        return next(iter(inputs.values()), "")

    parts = []
    for key, template in node.with_.items():
        value = _INPUT_REF.sub(lambda m: inputs.get(m.group(1), ""), template)
        value = _STEP_REF.sub(lambda m: outputs.get(m.group(1), ""), value)
        parts.append(value if len(node.with_) == 1 else f"{key}:\n{value}")
    return "\n\n".join(parts)
