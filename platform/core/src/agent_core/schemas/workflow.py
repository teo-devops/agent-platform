"""The ``kind: Workflow`` manifest.

A workflow composes existing agents into a deterministic pipeline. The nodes
are references to agent manifests, so the same agent can be used standalone and
as a step of several workflows without being redefined.

The manifest has two forms of the same document. The **authored** form says the
shape of the pipeline (``type: sequential``) and lets the platform work out the
rest; the **resolved** form, produced by :mod:`agent_core.publish`, spells
everything out (``needs``, pinned agent versions) so that whoever schedules it
does not have to know what ``sequential`` means. Same ``kind``, same
``apiVersion``, same schema — one is just the other with the blanks filled in.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from ..version import API_VERSION
from .common import (
    EvalSpec,
    GuardrailsSpec,
    InputSpec,
    Metadata,
    PermissionSpec,
    PluginRef,
    PolicySpec,
    Spec,
)

WorkflowType = Literal["sequential", "parallel", "loop", "graph"]

START = "START"


class NodeSpec(Spec):
    """One step of a workflow: a named reference to an agent manifest."""

    name: str = Field(description="Nombre del paso dentro del flujo. Único.")
    agent: str = Field(description="Agente que lo ejecuta. Al publicar se pinnea a `nombre@X.Y.Z`.")
    description: str = Field(default="", description="Qué aporta este paso.")
    needs: list[str] = Field(
        default_factory=list,
        description="Pasos que deben terminar antes. Normalmente se deja vacío y "
                    "se deduce de `type`; la forma publicada siempre lo trae escrito.",
    )
    retries: int | None = Field(
        default=None, ge=0, le=10,
        description="Reintentos del paso. Reintentar es cosa de quien orquesta, "
                    "por eso este límite viaja con el paso y el resto de `policies` no.",
    )
    with_: dict[str, str] = Field(
        default_factory=dict, alias="with",
        description="De dónde lee cada parámetro: `{{ inputs.x }}` o `{{ steps.y.output }}`. "
                    "Vacío, cada runtime pasa el estado como sepa.",
    )


class EdgeSpec(Spec):
    """A directed edge between two nodes; ``from: START`` marks an entry point."""

    from_: str = Field(alias="from", description="Nodo origen, o `START` para una entrada del flujo.")
    to: str = Field(description="Nodo destino.")


class WorkflowBody(Spec):
    type: WorkflowType = Field(
        default="sequential",
        description="Forma del flujo: `sequential` en línea, `parallel` en abanico, "
                    "`loop` repitiendo, `graph` con las aristas escritas a mano.",
    )
    runtime: str | None = Field(
        default=None,
        description="Framework que lo ejecuta. Ojo: LCEL no sabe de grafos ni bucles, "
                    "así que `graph` y `loop` sólo corren en adk o langgraph.",
    )
    nodes: list[NodeSpec] = Field(default_factory=list, description="Los pasos, en orden de declaración.")
    edges: list[EdgeSpec] = Field(default_factory=list, description="Sólo para `type: graph`: la topología, arista a arista.")
    max_iterations: int | None = Field(default=None, ge=1, description="Sólo para `type: loop`: cuántas vueltas como mucho.")
    inputs: list[InputSpec] = Field(default_factory=list, description="Parámetros de entrada, referenciados como `{{ inputs.nombre }}`.")
    eval: EvalSpec | None = Field(default=None, description="Puerta de calidad sobre el resultado del flujo.")
    guardrails: GuardrailsSpec = Field(default_factory=GuardrailsSpec, description="Guardrails de todo el flujo, además de los de cada agente.")
    policies: PolicySpec = Field(default_factory=PolicySpec, description="Límites operativos del flujo.")
    permissions: PermissionSpec = Field(default_factory=PermissionSpec, description="Qué agentes puede componer este flujo.")
    plugins: list[PluginRef] = Field(default_factory=list, description="Plugins extra a nivel de flujo.")

    @model_validator(mode="after")
    def _validate_topology(self) -> "WorkflowBody":
        names = {node.name for node in self.nodes}
        if len(names) != len(self.nodes):
            raise ValueError("workflow node names must be unique")

        for node in self.nodes:
            if node.name in node.needs:
                raise ValueError(f"node '{node.name}' cannot depend on itself")
            for dependency in node.needs:
                if dependency not in names:
                    raise ValueError(
                        f"node '{node.name}' needs unknown node '{dependency}'"
                    )

        if self.type == "graph":
            if not self.edges:
                raise ValueError("a 'graph' workflow needs at least one edge")
            for edge in self.edges:
                for endpoint in (edge.from_, edge.to):
                    if endpoint != START and endpoint not in names:
                        raise ValueError(f"edge references unknown node '{endpoint}'")
            if not any(edge.from_ == START for edge in self.edges):
                raise ValueError("a 'graph' workflow needs an edge starting at START")
        elif not self.nodes:
            raise ValueError(f"a '{self.type}' workflow needs at least one node")
        return self


class WorkflowManifest(Spec):
    apiVersion: str = API_VERSION
    kind: Literal["Workflow"] = "Workflow"
    metadata: Metadata
    spec: WorkflowBody = Field(default_factory=WorkflowBody)
    source_dir: Path | None = Field(default=None, exclude=True)

    @property
    def name(self) -> str:
        return self.metadata.name
