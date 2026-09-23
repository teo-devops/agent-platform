"""What gets deployed, and how: ``deploy/kagent/release.yaml``.

The agent manifest says *what an agent is*. Which agents run on a cluster, in
which mode and with which images is a deployment decision, so it lives next to
the deployment and not inside ``agent.yaml``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from agent_core.errors import ConfigError
from pydantic import BaseModel, ConfigDict, Field, ValidationError

API_VERSION = "deploy.agents.platform/v1"
KIND = "KagentRelease"


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ModelProvider(_Model):
    """Where kagent reads the model credentials from."""

    provider: Literal["Gemini"] = Field(default="Gemini", description="Proveedor de kagent. Hoy sólo Gemini.")
    api_key_secret: str = Field(default="kagent-gemini", description="Secret con la clave.")
    api_key_secret_key: str = Field(default="GOOGLE_API_KEY", description="Clave dentro del Secret.")


class ToolServer(_Model):
    """The MCP server that publishes ``catalog/tools`` to declarative agents."""

    name: str = "catalog-tools"
    image: str
    port: int = 8000
    tools: list[str] = Field(default_factory=lambda: ["*"], description="Globs de las tools publicadas.")


class Host(_Model):
    """The image that runs BYO agents (``agentctl kagent host``)."""

    image: str


class Skills(_Model):
    """Where kagent pulls skill images from (built by ``make skills``)."""

    registry: str = Field(description="Registro desde el que tira el init container de kagent.")
    insecure: bool = Field(default=True, description="Registro HTTP de laboratorio.")


class TrustBundle(_Model):
    """A CA bundle mounted into every pod that calls the model (TLS-intercepting networks)."""

    config_map: str
    key: str = "ca-certificates.crt"


class AgentRelease(_Model):
    name: str
    mode: Literal["declarative", "byo"]
    runtime: Literal["langgraph", "langchain"] | None = Field(
        default=None, description="Sólo byo: framework que ejecuta el agente dentro del pod."
    )


class ReleaseBody(_Model):
    namespace: str = "kagent"
    environment: str = "local"
    image_pull_policy: Literal["Always", "IfNotPresent", "Never"] = Field(
        default="IfNotPresent",
        description="Para las imágenes propias (host BYO y tool server). Always si la etiqueta se reutiliza.",
    )
    model: ModelProvider = Field(default_factory=ModelProvider)
    tool_server: ToolServer
    host: Host
    skills: Skills
    trust_bundle: TrustBundle | None = None
    a2a_gateway: str = Field(
        default="http://kagent-controller.kagent:8083/api/a2a",
        description="Dónde atiende A2A el controlador de kagent. Un agente BYO que delega "
                    "llama a <a2aGateway>/<namespace>/<agente>/.",
    )
    agents: list[AgentRelease]


class Release(_Model):
    apiVersion: Literal["deploy.agents.platform/v1"] = API_VERSION
    kind: Literal["KagentRelease"] = KIND
    metadata: dict = Field(default_factory=dict)
    spec: ReleaseBody

    @classmethod
    def load(cls, path: str | Path) -> "Release":
        path = Path(path)
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except FileNotFoundError:
            raise ConfigError(f"no release file at {path}") from None
        try:
            return cls.model_validate(_snake(data))
        except ValidationError as exc:
            raise ConfigError(f"{path}: {exc}") from None


def _snake(data):
    """Accept the camelCase keys a Kubernetes-flavoured YAML naturally uses."""
    if isinstance(data, dict):
        out = {}
        for key, value in data.items():
            if key not in ("apiVersion",):
                key = "".join("_" + c.lower() if c.isupper() else c for c in key)
            out[key] = _snake(value)
        return out
    if isinstance(data, list):
        return [_snake(item) for item in data]
    return data
