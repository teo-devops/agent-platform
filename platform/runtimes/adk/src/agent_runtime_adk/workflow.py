"""``kind: Workflow`` on Google ADK.

The shape of the pipeline is worked out once, framework-free, in
``agent_core.topology``; this only maps those names onto ADK objects.
"""

from __future__ import annotations

from typing import Any

from agent_core.errors import BuildError
from agent_core.schemas import WorkflowManifest
from agent_core.telemetry import get_logger, log_event
from agent_core.result import BuildResult
from agent_core.schemas.workflow import START as START_TOKEN
from agent_core.topology import edges as topology_edges
from google.adk import Workflow
from google.adk.agents import LoopAgent

from google.adk.workflow import START, JoinNode

from .plugins import build_plugins

logger = get_logger("adk.workflow")


class WorkflowBuilder:
    """Composes existing agents into a deterministic pipeline."""

    kind = "Workflow"
    runtime = "adk"

    def build(self, manifest: WorkflowManifest, factory: Any) -> BuildResult:
        body = manifest.spec
        name = manifest.metadata.python_name

        agents: dict[str, Any] = {}
        plugins: list[Any] = []

        for node in body.nodes:
            if not body.permissions.agents.permits(node.agent):
                raise BuildError(
                    f"workflow '{manifest.name}' uses agent '{node.agent}', "
                    f"which its permissions.agents rules do not allow"
                )
            child = factory.build(node.agent)
            _rename(child, node.name)
            agents[node.name] = child.agent
            plugins.extend(child.plugins)

        ordered = [agents[node.name] for node in body.nodes]

        if body.type == "loop":
            root: Any = LoopAgent(
                name=name,
                description=manifest.metadata.description,
                sub_agents=ordered,
                max_iterations=body.max_iterations or 3,
            )
        else:
            # The topology is decided framework-free; here it is only mapped
            # onto ADK's own START sentinel and agent objects.
            pairs = topology_edges(body)
            edges = [
                (START if origin == START_TOKEN else agents[origin], agents[target])
                for origin, target in pairs
            ]
            # ADK 2.x allows one terminal output per workflow. Branches that end
            # side by side (a `parallel` workflow, or a graph with several
            # leaves) are closed with a join, which waits for all of them and
            # outputs their results together.
            origins = {origin for origin, _ in pairs}
            terminals = [agents[n.name] for n in body.nodes if n.name not in origins]
            if len(terminals) > 1:
                join = JoinNode(name=f"{name}_join")
                edges += [(terminal, join) for terminal in terminals]
            root = Workflow(
                name=name,
                description=manifest.metadata.description,
                edges=edges,
            )

        plugins = build_plugins(
            agent="",  # workflow-level plugins are not scoped to a single agent
            guardrails=body.guardrails,
            policies=body.policies,
            permissions=body.permissions,
            extra=body.plugins,
            registry=factory.registries.plugins,
            audit=False,  # each step already carries its own audit plugin
        ) + plugins

        log_event(
            logger,
            "workflow built",
            workflow=manifest.name,
            type=body.type,
            steps=[node.name for node in body.nodes],
        )
        return BuildResult(agent=root, plugins=plugins, manifest=manifest)


def _rename(result: BuildResult, node_name: str) -> None:
    """Give a step the name the workflow uses for it.

    The same agent may appear as two steps of one pipeline, and ADK requires
    unique names, so the node name wins. Plugin scopes are re-pointed at the
    new name; otherwise the guardrails built for that agent would stop matching
    its callbacks.
    """
    new_name = node_name.replace("-", "_")
    old_name = result.agent.name
    if new_name == old_name:
        return

    result.agent.name = new_name
    for plugin in result.plugins:
        if getattr(plugin, "agent", None) == old_name:
            plugin.agent = new_name
