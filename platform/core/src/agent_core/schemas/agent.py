"""The ``kind: Agent`` manifest."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field

from ..version import API_VERSION
from .common import (
    GuardrailsSpec,
    Metadata,
    ModelSpec,
    PermissionSpec,
    PluginRef,
    PolicySpec,
    PromptSpec,
    SkillRef,
    Spec,
    SubAgentRef,
    ToolRef,
)


class AgentBody(Spec):
    """Everything that can be changed about an agent without touching code."""

    runtime: str | None = Field(
        default=None,
        description="Framework que lo ejecuta: adk, langgraph o langchain. "
                    "Vacío, se aplica el de configs/defaults.yaml.",
    )
    model: ModelSpec = Field(default_factory=ModelSpec, description="Qué modelo responde y con qué ajustes.")
    prompt: PromptSpec = Field(default_factory=PromptSpec, description="Las instrucciones del agente.")
    tools: list[ToolRef] = Field(default_factory=list, description="Herramientas que puede llamar.")
    skills: list[SkillRef] = Field(
        default_factory=list,
        description="Skills del catálogo. Sólo su descripción viaja en el prompt; "
                    "el cuerpo lo pide el agente con `skill.read`.",
    )
    sub_agents: list[SubAgentRef] = Field(default_factory=list, description="Agentes a los que puede delegar.")
    guardrails: GuardrailsSpec = Field(default_factory=GuardrailsSpec, description="Qué se comprueba antes y después del modelo.")
    policies: PolicySpec = Field(default_factory=PolicySpec, description="Cuánto trabajo puede hacer una invocación.")
    permissions: PermissionSpec = Field(default_factory=PermissionSpec, description="Qué puede alcanzar. Se comprueba al construir y al llamar.")
    plugins: list[PluginRef] = Field(default_factory=list, description="Plugins extra, más allá de los derivados de lo anterior.")
    output_key: str | None = Field(
        default=None,
        description="Nombre con el que su respuesta queda en el estado compartido, "
                    "para que otro paso la lea.",
    )

    @property
    def enabled_skills(self) -> list[SkillRef]:
        return [skill for skill in self.skills if skill.enabled]

    @property
    def enabled_tools(self) -> list[ToolRef]:
        return [tool for tool in self.tools if tool.enabled]

    @property
    def enabled_sub_agents(self) -> list[SubAgentRef]:
        return [sub for sub in self.sub_agents if sub.enabled]


class AgentManifest(Spec):
    """A validated ``agent.yaml`` plus the directory it was loaded from."""

    apiVersion: str = API_VERSION
    kind: Literal["Agent"] = "Agent"
    metadata: Metadata
    spec: AgentBody = Field(default_factory=AgentBody)
    source_dir: Path | None = Field(default=None, exclude=True)

    @property
    def name(self) -> str:
        return self.metadata.name
