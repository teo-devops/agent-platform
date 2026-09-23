"""``kind: Workflow`` on LangChain.

LangChain composes with LCEL: runnables piped into a sequence, or run side by
side with ``RunnableParallel``. That covers a line and a fan-out, which is what
``sequential`` and ``parallel`` are.

It does **not** cover an arbitrary DAG or a loop, and this module says so
instead of approximating. LCEL is chains, not graphs — a workflow that needs a
real graph belongs on the langgraph or adk runtime, and the error says which.
That limit is the honest reason the three runtimes are not interchangeable in
every case, and it is worth seeing rather than hiding.
"""

from __future__ import annotations

import re
from typing import Any

from agent_core.errors import BuildError
from agent_core.result import BuildResult
from agent_core.schemas import WorkflowManifest
from agent_core.telemetry import get_logger, log_event

logger = get_logger("langchain.workflow")

_INPUT_REF = re.compile(r"{{\s*inputs\.([a-zA-Z0-9_]+)\s*}}")
_STEP_REF = re.compile(r"{{\s*steps\.([a-zA-Z0-9_-]+)\.output\s*}}")


class WorkflowBuilder:
    """Composes existing agents into an LCEL chain."""

    kind = "Workflow"
    runtime = "langchain"

    def build(self, manifest: WorkflowManifest, factory: Any) -> BuildResult:
        from langchain_core.runnables import RunnableLambda, RunnableParallel

        body = manifest.spec

        if body.type in ("loop", "graph"):
            raise BuildError(
                f"workflow '{manifest.name}' is of type '{body.type}', which LCEL "
                f"cannot express: it composes chains, not graphs, and has no "
                f"repetition construct. Run it on the langgraph or adk runtime."
            )

        children: dict[str, BuildResult] = {}
        plugins: list[Any] = []

        for node in body.nodes:
            if not body.permissions.agents.permits(node.agent):
                raise BuildError(
                    f"workflow '{manifest.name}' uses agent '{node.agent}', "
                    f"which its permissions.agents rules do not allow"
                )
            child = factory.build(node.agent)
            children[node.name] = child
            plugins.extend(child.plugins)

        if body.type == "parallel":
            # Every branch sees the same input and they run side by side.
            root: Any = RunnableParallel(
                **{
                    node.name: RunnableLambda(_step(node, children[node.name]))
                    for node in body.nodes
                }
            )
        else:
            chain = RunnableLambda(_step(body.nodes[0], children[body.nodes[0].name]))
            for node in body.nodes[1:]:
                chain = chain | RunnableLambda(_step(node, children[node.name]))
            root = chain

        log_event(
            logger,
            "workflow built",
            workflow=manifest.name,
            runtime="langchain",
            type=body.type,
            steps=[node.name for node in body.nodes],
        )
        return BuildResult(agent=root, plugins=plugins, manifest=manifest)


def _step(node: Any, child: BuildResult) -> Any:
    """One link of the chain: take what came before, run the agent, pass it on."""

    def run(payload: Any) -> str:
        answer = child.agent.invoke(
            {"messages": [{"role": "user", "content": _request(node, payload)}]}
        )
        messages = answer.get("messages", [])
        return messages[-1].text if messages else ""

    return run


def _request(node: Any, payload: Any) -> str:
    """Resolve ``with`` against what arrived, or just pass the text through."""
    if isinstance(payload, str):
        text, inputs, outputs = payload, {}, {}
    else:
        inputs = payload.get("inputs", {})
        outputs = payload.get("outputs", {})
        text = next(iter(inputs.values()), "")

    if not node.with_:
        return text

    parts = []
    for key, template in node.with_.items():
        value = _INPUT_REF.sub(lambda m: inputs.get(m.group(1), text), template)
        value = _STEP_REF.sub(lambda m: outputs.get(m.group(1), text), value)
        parts.append(value if len(node.with_) == 1 else f"{key}:\n{value}")
    return "\n\n".join(parts)
