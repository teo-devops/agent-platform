"""Discovery and resolution of the declarative configuration tree.

Layout expected under the repository root::

    agents/<name>/agent.yaml        one directory per agent
    workflows/<name>.yaml           workflow manifests
    configs/defaults.yaml           fleet-wide defaults
    configs/models.yaml             named model profiles
    configs/guardrails.yaml         named guardrail profiles
    configs/policies.yaml           named policy profiles
    configs/permissions.yaml        named permission profiles
    configs/environments/<env>.yaml per-environment overrides

Resolution order for an agent (later layers win)::

    configs/defaults.yaml:agentDefaults              fleet defaults
    configs/environments/<env>.yaml:agentDefaults    environment defaults
    agents/<name>/agent.yaml:spec                    what the agent asked for
    configs/environments/<env>.yaml:agents.<name>    targeted override

The two halves read differently on purpose. ``agentDefaults`` are *defaults*:
they fill in what an agent did not decide for itself, so an agent that pins a
model keeps it in every environment. ``agents.<name>`` is an *override*: it is
how an environment forces a specific agent onto a different model, budget or
guardrail profile without touching the manifest.

Profiles (``model.profile``, ``policies.profile``, ...) are expanded *after*
merging, and explicit keys always beat the profile they inherit from.
"""

from __future__ import annotations

import os
from functools import cached_property
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from ..errors import ConfigError
from ..schemas import AgentManifest, WorkflowManifest

if TYPE_CHECKING:  # pragma: no cover
    from ..skills import SkillSet
from .merge import interpolate, merge_all, render_template

DEFAULT_ENVIRONMENT = "local"

_PROFILE_SECTIONS = {
    "model": "models",
    "guardrails": "guardrails",
    "policies": "policies",
    "permissions": "permissions",
}


def load_yaml(path: Path) -> dict[str, Any]:
    """Read a YAML file into a dict, with env interpolation applied."""
    if not path.exists():
        return {}
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path}: invalid YAML: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"{path}: expected a mapping at the top level")
    return interpolate(raw)


#: Where the catalogue lives, relative to the platform root. The framework is in
#: `platform/` and what changes every day is here — the split is the point.
CATALOG_DIR = "catalog"
AGENTS_DIR = f"{CATALOG_DIR}/agents"
WORKFLOWS_DIR = f"{CATALOG_DIR}/workflows"
SKILLS_DIR = f"{CATALOG_DIR}/skills"
TOOLS_DIR = f"{CATALOG_DIR}/tools"


class ConfigStore:
    """Reads the configuration tree and produces validated manifests."""

    def __init__(self, root: str | Path, environment: str | None = None) -> None:
        self.root = Path(root).resolve()
        self.environment = environment or os.getenv("AGENT_ENV", DEFAULT_ENVIRONMENT)
        if not self.root.exists():
            raise ConfigError(f"configuration root '{self.root}' does not exist")

    # -- raw layers ---------------------------------------------------------

    @cached_property
    def defaults(self) -> dict[str, Any]:
        return load_yaml(self.root / "configs" / "defaults.yaml")

    @cached_property
    def environment_overlay(self) -> dict[str, Any]:
        path = self.root / "configs" / "environments" / f"{self.environment}.yaml"
        if not path.exists():
            raise ConfigError(
                f"unknown environment '{self.environment}': {path} not found. "
                f"Available: {', '.join(self.list_environments()) or '<none>'}"
            )
        return load_yaml(path)

    @cached_property
    def remote_agents(self) -> dict[str, str]:
        """Agents that run in another process, and the A2A URL they answer at.

        Where an agent runs is a deployment decision, so it is not in its
        manifest: a ``sub_agents`` entry reads the same whether the child is
        built in-process or called over A2A. Two sources, the variable wins::

            # configs/environments/<env>.yaml
            a2a:
              endpoints:
                python-developer: http://localhost:9101

            AGENT_A2A_ENDPOINTS="python-developer=http://localhost:9101,code-reviewer=..."

        The variable is what ``agentctl kagent render`` writes into a BYO pod.
        """
        block = self.environment_overlay.get("a2a") or {}
        endpoints = {str(k): str(v) for k, v in (block.get("endpoints") or {}).items()}
        for pair in filter(None, (p.strip() for p in os.getenv("AGENT_A2A_ENDPOINTS", "").split(","))):
            name, sep, url = pair.partition("=")
            if not sep or not name.strip() or not url.strip():
                raise ConfigError(f"AGENT_A2A_ENDPOINTS: '{pair}' is not 'agent=url'")
            endpoints[name.strip()] = url.strip()
        return endpoints

    def profiles(self, section: str) -> dict[str, Any]:
        """Named profiles of a configs file (``models`` -> ``configs/models.yaml``)."""
        data = load_yaml(self.root / "configs" / f"{section}.yaml")
        return data.get("profiles", {})

    # -- listings -----------------------------------------------------------

    def list_environments(self) -> list[str]:
        env_dir = self.root / "configs" / "environments"
        return sorted(p.stem for p in env_dir.glob("*.yaml")) if env_dir.exists() else []

    @cached_property
    def agent_paths(self) -> dict[str, Path]:
        """Every agent in the catalogue, indexed by name.

        Agents are grouped in domain folders (``catalog/agents/health/...``) so
        that a catalogue of fifty does not become one flat listing. The domain is
        filing, not identity: an agent is referenced by its name and moving it
        between folders changes nothing.
        """
        agents_dir = self.root / AGENTS_DIR
        if not agents_dir.exists():
            return {}

        found: dict[str, Path] = {}
        for path in sorted(agents_dir.rglob("agent.yaml")):
            name = path.parent.name
            if name in found:
                raise ConfigError(
                    f"two agents are called '{name}': {found[name]} and {path}. "
                    f"Names are global; the domain folder does not namespace them."
                )
            found[name] = path
        return found

    def list_agents(self) -> list[str]:
        return sorted(self.agent_paths)

    def list_workflows(self) -> list[str]:
        workflows_dir = self.root / WORKFLOWS_DIR
        return sorted(p.stem for p in workflows_dir.glob("*.yaml")) if workflows_dir.exists() else []

    def domain_of(self, name: str) -> str:
        """Which domain folder an agent is filed under, for listings."""
        path = self.agent_paths.get(name)
        if path is None:
            return ""
        relative = path.parent.relative_to(self.root / AGENTS_DIR).parent
        return "" if str(relative) == "." else str(relative)

    def list_skills(self) -> list[str]:
        skills_dir = self.root / SKILLS_DIR
        if not skills_dir.exists():
            return []
        return sorted(p.parent.name for p in skills_dir.glob("*/SKILL.md"))

    def load_skill(self, name: str):
        """Cargar una skill del catálogo."""
        from ..skills import load_skill

        directory = self.root / SKILLS_DIR / name
        if not (directory / "SKILL.md").exists():
            raise ConfigError(
                f"unknown skill '{name}': no hay {SKILLS_DIR}/{name}/SKILL.md. "
                f"Disponibles: {', '.join(self.list_skills()) or '<ninguna>'}"
            )
        return load_skill(directory)

    def resolve_skills(self, refs) -> "SkillSet":
        """Resolver las referencias de un agente a skills concretas.

        Aquí se comprueba el rango de versión: una skill que no lo cumpla es un
        error de construcción, no un aviso. Si un agente dice `@^1.0` y en el
        catálogo hay una 2.0.0, el cuerpo de instrucciones ha cambiado de forma
        incompatible y seguir adelante sería fingir que no.
        """
        from ..skills import SkillSet, parse_ref, satisfies

        resueltas = []
        for ref in refs:
            nombre, rango = parse_ref(ref.ref if hasattr(ref, "ref") else str(ref))
            skill = self.load_skill(nombre)
            if not satisfies(skill.version, rango):
                raise ConfigError(
                    f"la skill '{nombre}' está en v{skill.version} y se pidió '{rango}'"
                )
            resueltas.append(skill)
        return SkillSet(resueltas)

    # -- loading ------------------------------------------------------------

    def load_agent(self, name: str) -> AgentManifest:
        """Load, merge, resolve and validate one agent manifest."""
        path = self.agent_paths.get(name)
        if path is None:
            raise ConfigError(
                f"unknown agent '{name}': no agent.yaml for it under {AGENTS_DIR}/. "
                f"Available: {', '.join(self.list_agents()) or '<none>'}"
            )
        raw = load_yaml(path)
        self._check_kind(raw, expected="Agent", path=path)

        body = merge_all(
            self.defaults.get("agentDefaults", {}),
            self.environment_overlay.get("agentDefaults", {}),
            raw.get("spec", {}),
            self.environment_overlay.get("agents", {}).get(name, {}),
        )
        body = self._resolve_profiles(body)
        body = self._resolve_prompt(body, path.parent)

        manifest = AgentManifest.model_validate(
            {
                "apiVersion": raw.get("apiVersion", AgentManifest.model_fields["apiVersion"].default),
                "kind": "Agent",
                "metadata": {**raw.get("metadata", {}), "name": raw.get("metadata", {}).get("name", name)},
                "spec": body,
                "source_dir": path.parent,
            }
        )
        if manifest.name != name:
            raise ConfigError(f"{path}: metadata.name '{manifest.name}' does not match directory '{name}'")
        return manifest

    def load_workflow(self, name: str) -> WorkflowManifest:
        """Load, merge, resolve and validate one workflow manifest."""
        path = self.root / WORKFLOWS_DIR / f"{name}.yaml"
        if not path.exists():
            raise ConfigError(
                f"unknown workflow '{name}': {path} not found. "
                f"Available: {', '.join(self.list_workflows()) or '<none>'}"
            )
        raw = load_yaml(path)
        self._check_kind(raw, expected="Workflow", path=path)

        body = merge_all(
            self.defaults.get("workflowDefaults", {}),
            self.environment_overlay.get("workflowDefaults", {}),
            raw.get("spec", {}),
            self.environment_overlay.get("workflows", {}).get(name, {}),
        )
        body = self._resolve_profiles(body)

        manifest = WorkflowManifest.model_validate(
            {
                "apiVersion": raw.get("apiVersion", WorkflowManifest.model_fields["apiVersion"].default),
                "kind": "Workflow",
                "metadata": {**raw.get("metadata", {}), "name": raw.get("metadata", {}).get("name", name)},
                "spec": body,
                "source_dir": path.parent,
            }
        )
        return manifest

    def load(self, name: str) -> AgentManifest | WorkflowManifest:
        """Load ``name`` whether it is an agent or a workflow."""
        if name in self.list_agents():
            return self.load_agent(name)
        if name in self.list_workflows():
            return self.load_workflow(name)
        raise ConfigError(
            f"'{name}' is neither a known agent nor a known workflow. "
            f"Agents: {', '.join(self.list_agents()) or '<none>'} | "
            f"Workflows: {', '.join(self.list_workflows()) or '<none>'}"
        )

    # -- internals ----------------------------------------------------------

    @staticmethod
    def _check_kind(raw: dict[str, Any], *, expected: str, path: Path) -> None:
        kind = raw.get("kind", expected)
        if kind != expected:
            raise ConfigError(f"{path}: expected kind '{expected}', found '{kind}'")

    def _resolve_profiles(self, body: dict[str, Any]) -> dict[str, Any]:
        """Expand every ``profile:`` reference, keeping explicit keys on top."""
        resolved = dict(body)
        for section, source in _PROFILE_SECTIONS.items():
            block = resolved.get(section)
            if not isinstance(block, dict):
                continue
            profile_name = block.get("profile")
            if not profile_name:
                continue
            profiles = self.profiles(source)
            if profile_name not in profiles:
                raise ConfigError(
                    f"unknown {source} profile '{profile_name}'. "
                    f"Available: {', '.join(sorted(profiles)) or '<none>'}"
                )
            resolved[section] = merge_all(profiles[profile_name], block)
        return resolved

    @staticmethod
    def _resolve_prompt(body: dict[str, Any], agent_dir: Path) -> dict[str, Any]:
        """Inline ``prompt.file`` and render ``{{ variables }}``."""
        prompt = body.get("prompt")
        if not isinstance(prompt, dict):
            return body
        prompt = dict(prompt)
        file_ref = prompt.pop("file", None)
        if file_ref:
            prompt_path = (agent_dir / file_ref).resolve()
            if not prompt_path.exists():
                raise ConfigError(f"prompt file '{prompt_path}' not found")
            if prompt.get("instruction"):
                raise ConfigError("prompt: set either 'instruction' or 'file', not both")
            prompt["instruction"] = prompt_path.read_text(encoding="utf-8").strip()

        variables = prompt.get("variables") or {}
        for key in ("instruction", "global_instruction"):
            if prompt.get(key) and variables:
                prompt[key] = render_template(prompt[key], variables)

        body = dict(body)
        body["prompt"] = prompt
        return body
