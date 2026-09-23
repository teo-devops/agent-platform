"""The resolved form of a manifest: same document, with the blanks filled in.

This is **not** a translation. There is one vocabulary in this platform
(``agents.platform/v1``) and whoever consumes a manifest — an orchestrator, a
catalogue, another team — reads that same vocabulary. What this module does is
answer the questions an author is allowed to leave implicit:

* ``type: sequential`` says the shape; the resolved form spells out ``needs``.
* ``agent: researcher`` says which agent; the resolved form pins
  ``researcher@0.1.0``, because a floating reference runs something different
  depending on the day.
* profiles and environment overlays are already expanded by the store, so what
  gets published is what would actually run.

Both forms validate against the same generated schema. One is just the other
with nothing left to work out.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import ConfigError
from .schemas import START, AgentManifest, WorkflowBody, WorkflowManifest

#: Name of the input synthesised for a workflow that declares none.
ENTRY_INPUT = "message"


@dataclass(frozen=True)
class Resolved:
    """A manifest ready to hand to whoever runs it."""

    kind: str
    name: str
    path: str
    document: dict[str, Any]

    def write(self, directory: Path) -> Path:
        import yaml

        target = Path(directory) / self.path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            yaml.safe_dump(
                self.document, sort_keys=False, allow_unicode=True, default_flow_style=False
            ),
            encoding="utf-8",
        )
        return target


def resolve(manifest: AgentManifest | WorkflowManifest, store: Any) -> Resolved:
    """Resolve any manifest the store can load."""
    if isinstance(manifest, AgentManifest):
        return resolve_agent(manifest, store)
    if isinstance(manifest, WorkflowManifest):
        return resolve_workflow(manifest, store)
    raise ConfigError(f"cannot resolve a manifest of type {type(manifest).__name__}")


def resolve_agent(manifest: AgentManifest, store: Any) -> Resolved:
    """An agent, with its delegations pinned to exact versions."""
    document = _dump(manifest)
    spec = document["spec"]

    for sub in spec.get("sub_agents", []):
        sub["ref"] = pin(sub["ref"], store)

    return Resolved(
        kind="Agent",
        name=manifest.name,
        path=f"agents/{manifest.name}.yaml",
        document=document,
    )


def resolve_workflow(manifest: WorkflowManifest, store: Any) -> Resolved:
    """A workflow, with its topology made explicit and its agents pinned."""
    body = manifest.spec
    document = _dump(manifest)
    spec = document["spec"]

    needs = dependencies(body)

    if not spec.get("inputs"):
        spec["inputs"] = [
            {
                "name": ENTRY_INPUT,
                "description": "Entrada del flujo, entregada a los pasos iniciales.",
            }
        ]
    entry = spec["inputs"][0]["name"]

    for node, raw in zip(body.nodes, spec["nodes"]):
        raw["needs"] = needs[node.name]
        raw["agent"] = pin(node.agent, store)
        if not raw.get("with"):
            raw["with"] = wiring(needs[node.name], entry)
        if raw.get("retries") is None:
            attempts = store.load_agent(node.agent).spec.policies.retry_attempts
            if attempts:
                raw["retries"] = max(0, min(attempts, 10))

    return Resolved(
        kind="Workflow",
        name=manifest.name,
        path=f"workflows/{manifest.name}.yaml",
        document=document,
    )


def dependencies(body: WorkflowBody) -> dict[str, list[str]]:
    """Make the implicit topology explicit.

    An author says the *shape* of a pipeline; a scheduler needs it per step.
    ``graph`` already carries its edges, and ``loop`` runs its nodes in order
    within each iteration — the repetition itself stays in ``max_iterations``,
    because flattening it would throw away the stopping condition.
    """
    names = [node.name for node in body.nodes]

    # An author who wrote `needs` by hand meant it; do not second-guess them.
    if any(node.needs for node in body.nodes):
        return {node.name: list(node.needs) for node in body.nodes}

    if body.type == "parallel":
        return {name: [] for name in names}

    if body.type == "graph":
        deps: dict[str, list[str]] = {name: [] for name in names}
        for edge in body.edges:
            if edge.from_ != START:
                deps[edge.to].append(edge.from_)
        return deps

    # sequential and loop
    return {
        name: ([names[index - 1]] if index else [])
        for index, name in enumerate(names)
    }


def wiring(needs: list[str], entry_input: str = ENTRY_INPUT) -> dict[str, str]:
    """Where each step reads its input from.

    An entry step reads the workflow input; every other step reads the output of
    what it depends on. A runtime is free to pass state its own way — this is
    the explicit version, for whoever cannot see inside the framework.
    """
    if not needs:
        return {entry_input: f"{{{{ inputs.{entry_input} }}}}"}
    if len(needs) == 1:
        return {"input": f"{{{{ steps.{needs[0]}.output }}}}"}
    return {f"input_{dep}": f"{{{{ steps.{dep}.output }}}}" for dep in needs}


def pin(agent: str, store: Any) -> str:
    """Turn a floating agent reference into an immutable one."""
    if "@" in agent:
        return agent
    referenced = store.load_agent(agent)
    return f"{agent}@{referenced.metadata.version}"


def _dump(manifest: AgentManifest | WorkflowManifest) -> dict[str, Any]:
    return manifest.model_dump(mode="json", exclude_none=True, by_alias=True)
