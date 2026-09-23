"""Schema fragments shared by agent and workflow manifests."""

from __future__ import annotations

import fnmatch
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

_NAME_RE = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$")


class Spec(BaseModel):
    """Base model: unknown keys are rejected so typos fail loudly at validation."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class Metadata(Spec):
    """Identity of a manifest. ``name`` is the reference used everywhere else."""

    name: str = Field(description="Referencia con la que se le llama desde todas partes. Minúsculas, dígitos y guiones.")
    version: str = Field(default="0.1.0", description="SemVer. Es lo que se pinnea al publicar el manifiesto.")
    description: str = Field(default="", description="Una línea: qué hace y cuándo usarlo.")
    owner: str = Field(default="unassigned", description="Equipo responsable. Aparece como label al publicar.")
    tags: list[str] = Field(default_factory=list, description="Etiquetas libres para buscar y agrupar.")
    labels: dict[str, str] = Field(default_factory=dict, description="Metadatos clave/valor para quien consuma el manifiesto.")

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: str) -> str:
        if not _NAME_RE.match(value):
            raise ValueError(
                f"'{value}' is not a valid name: use lowercase letters, digits and dashes"
            )
        return value

    @property
    def python_name(self) -> str:
        """The name in the identifier form runtimes require (``health_advisor``)."""
        return self.name.replace("-", "_")


class ModelSpec(Spec):
    """Which model answers, and with what generation settings.

    ``profile`` resolves against ``configs/models.yaml``; any field set here
    overrides the profile, so an agent can inherit a fleet-wide profile and
    still pin one knob.
    """

    profile: str | None = Field(default=None, description="Perfil de configs/models.yaml del que se hereda. Lo que se ponga aquí explícito gana.")
    name: str | None = Field(default=None, description="Modelo concreto. Déjalo vacío salvo que tengas un motivo: el perfil existe para no atarse a uno.")
    temperature: float | None = Field(default=None, ge=0.0, le=2.0, description="Cuánto se aparta el modelo de la respuesta más probable.")
    top_p: float | None = Field(default=None, ge=0.0, le=1.0, description="Muestreo por núcleo. Lo soportan los tres runtimes.")
    top_k: int | None = Field(default=None, ge=1, description="Muestreo por k. Gemini lo tiene; OpenAI no. Un runtime que no lo entienda lo ignora avisando.")
    max_output_tokens: int | None = Field(default=None, ge=1, description="Techo de tokens de la respuesta.")
    stop_sequences: list[str] = Field(default_factory=list, description="Cadenas que cortan la generación. No todos los proveedores las aplican igual.")


class PromptSpec(Spec):
    """The agent's instructions.

    Either inline ``instruction`` text or ``file`` (relative to the manifest
    directory). ``variables`` are substituted as ``{{ name }}`` placeholders,
    which keeps prompt wording in configuration rather than in code.
    """

    instruction: str | None = Field(default=None, description="Las instrucciones, en línea. Excluyente con `file`.")
    file: str | None = Field(default=None, description="Ruta a un .md junto al manifiesto. Al resolver, su contenido pasa a `instruction`.")
    global_instruction: str | None = Field(default=None, description="Instrucción que también heredan los sub-agentes. Sólo la aplica el runtime adk.")
    variables: dict[str, str] = Field(default_factory=dict, description="Valores que sustituyen los `{{ nombre }}` del prompt.")


class ToolRef(Spec):
    """A reference to a registered tool, optionally disabled per environment."""

    ref: str = Field(description="Referencia registrada, p. ej. `health.calculate_bmi`. Mírales el nombre con `agentctl components`.")
    alias: str | None = Field(default=None, description="Otro nombre con el que el modelo verá la herramienta.")
    enabled: bool = Field(default=True, description="Ponlo a false en un overlay de entorno para quitarla sin tocar el manifiesto.")
    params: dict[str, Any] = Field(default_factory=dict, description="Parámetros fijos para la herramienta.")


class SubAgentRef(Spec):
    """How another agent is attached to this one.

    ``mode: tool`` wraps it as a callable tool (the coordinator keeps control);
    ``mode: transfer`` attaches it as an ADK sub-agent (control can move to it).
    """

    ref: str = Field(description="Nombre del agente delegado. Al publicar se pinnea a `nombre@X.Y.Z`.")
    mode: Literal["tool", "transfer"] = Field(default="tool", description="`tool`: el coordinador manda siempre. `transfer`: el turno pasa al hijo — sólo existe en adk.")
    alias: str | None = Field(default=None, description="Nombre con el que el coordinador ve al delegado.")
    description: str | None = Field(default=None, description="Cuándo debe delegar el coordinador. Es lo que lee el modelo para decidir.")
    enabled: bool = Field(default=True, description="Permite desactivar la delegación por entorno.")


class SkillRef(Spec):
    """Una skill del catálogo enganchada a este agente.

    Del cuerpo de la skill no se carga nada al construir: sólo su nombre y su
    descripción llegan al prompt, y el agente pide el resto con `skill.read` si
    le hace falta.
    """

    ref: str = Field(description="`nombre` o `nombre@rango`, p. ej. `hexagonal-architecture@^1.0`.")
    enabled: bool = Field(default=True, description="Permite desengancharla por entorno.")


class GuardrailRule(Spec):
    """One check applied to a piece of text at a given stage."""

    name: str = Field(description="Nombre de la regla. Aparece en la traza cuando salta.")
    type: Literal["regex_deny", "keywords_deny", "max_chars", "pii_redact"] = Field(description="Qué comprueba. Un tipo nuevo es código; una regla nueva es configuración.")
    action: Literal["block", "redact", "warn"] = Field(default="block", description="`block` corta, `redact` reescribe y sigue, `warn` sólo deja constancia.")
    message: str | None = Field(default=None, description="Qué se responde cuando bloquea.")
    params: dict[str, Any] = Field(default_factory=dict, description="Parámetros del tipo de regla (`keywords`, `patterns`, `limit`...).")


class GuardrailsSpec(Spec):
    """Guardrails grouped by the stage they run at."""

    profile: str | None = None
    input: list[GuardrailRule] = Field(default_factory=list)
    output: list[GuardrailRule] = Field(default_factory=list)
    tools: list[GuardrailRule] = Field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not (self.input or self.output or self.tools)


class BudgetSpec(Spec):
    """Cost ceilings for a single invocation."""

    max_tokens: int | None = Field(default=None, ge=1, description="Techo de tokens de una invocación.")
    max_usd: float | None = Field(default=None, ge=0, description="Declarado, todavía no contabilizado: hoy el corte se hace por tokens.")


class PolicySpec(Spec):
    """Operational limits enforced by the runtime, not by the model."""

    profile: str | None = Field(default=None, description="Perfil de configs/policies.yaml del que se hereda.")
    max_tool_calls: int | None = Field(default=None, ge=1, description="Techo de llamadas a herramienta por invocación.")
    max_llm_calls: int | None = Field(default=None, ge=1, description="Techo de llamadas al modelo por invocación.")
    timeout_seconds: float | None = Field(default=None, gt=0, description="Declarado y validado; todavía no lo aplica ningún runtime.")
    retry_attempts: int = Field(default=0, ge=0, description="Reintentos. Es el único límite que cruza al orquestador, como `retries` de cada paso.")
    budget: BudgetSpec = Field(default_factory=BudgetSpec, description="Techos de coste de una invocación.")


class AllowDeny(Spec):
    """Glob allow/deny lists. ``deny`` always wins over ``allow``."""

    allow: list[str] = Field(default_factory=lambda: ["*"], description="Patrones permitidos, p. ej. `[\"health.*\"]`.")
    deny: list[str] = Field(default_factory=list, description="Patrones prohibidos. `deny` gana siempre sobre `allow`.")

    def permits(self, ref: str) -> bool:
        if any(fnmatch.fnmatch(ref, pattern) for pattern in self.deny):
            return False
        return any(fnmatch.fnmatch(ref, pattern) for pattern in self.allow)


class PermissionSpec(Spec):
    """What an agent is allowed to reach.

    Checked twice: at build time (a denied tool is never attached) and at call
    time by the permissions plugin (a model cannot talk its way past it).
    """

    profile: str | None = Field(default=None, description="Perfil de configs/permissions.yaml del que se hereda.")
    tools: AllowDeny = Field(default_factory=AllowDeny, description="Qué herramientas puede alcanzar.")
    agents: AllowDeny = Field(default_factory=AllowDeny, description="A qué agentes puede delegar. Lista distinta de la de herramientas, a propósito.")


class InputSpec(Spec):
    """A parameter a workflow takes, referenced as ``{{ inputs.name }}``."""

    name: str = Field(description="Identificador, referenciado como `{{ inputs.nombre }}`.")
    description: str = Field(default="", description="Qué se espera en este parámetro.")
    default: str | None = Field(default=None, description="Valor si no se pasa ninguno.")

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: str) -> str:
        if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", value):
            raise ValueError(f"'{value}' is not a valid input name: use an identifier")
        return value


class EvalSpec(Spec):
    """A quality gate on the result of a workflow.

    Neutral on purpose: it says which metric matters and where the line is, not
    who measures it. Whoever runs the workflow decides that.
    """

    metric: str = Field(description="Métrica que decide, p. ej. `pass_at_1`.")
    threshold: float = Field(description="Dónde está la línea.")
    goal: Literal["maximize", "minimize"] = Field(default="maximize", description="De qué lado de la línea hay que estar.")


class PluginRef(Spec):
    """An extra runtime plugin, beyond those derived from the sections above."""

    ref: str = Field(description="Plugin registrado, más allá de los que salen de guardrails/permisos/política.")
    enabled: bool = Field(default=True, description="Permite desactivarlo por entorno.")
    config: dict[str, Any] = Field(default_factory=dict, description="Configuración que recibe el plugin.")
