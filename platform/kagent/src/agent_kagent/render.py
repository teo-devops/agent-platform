"""Manifests in, kagent CRDs out.

Every object written here is derived from ``agents.platform/v1`` manifests plus
the release file; nothing is typed twice. The mapping, field by field:

======================  ==================================================
agent.yaml              kagent (``kagent.dev/v1alpha2``)
======================  ==================================================
spec.model              ``ModelConfig`` ``<agent>-model``
spec.prompt             ``ConfigMap`` ``<agent>-prompt`` + ``systemMessageFrom``
spec.tools              ``tools[type=McpServer]`` → ``RemoteMCPServer``
spec.sub_agents (tool)  ``tools[type=Agent]`` — the call travels over A2A
spec.sub_agents (byo)   ``AGENT_A2A_ENDPOINTS`` — also A2A, via the controller
spec.skills             ``skills.refs`` — OCI images built by ``make skills``
metadata.version        label + ``OTEL_RESOURCE_ATTRIBUTES``
======================  ==================================================

What kagent's declarative runtime cannot express is reported, never dropped
silently: guardrails and policies are *warnings* (the agent still works, it is
just not enforced), a workflow or a ``mode: transfer`` sub-agent is an *error*
that suggests ``mode: byo``, where our own runtime enforces everything.
"""

from __future__ import annotations

import fnmatch
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from agent_core.errors import ConfigError
from agent_core.telemetry import agent_attributes

from .release import AgentRelease, Release

KAGENT_API = "kagent.dev/v1alpha2"
PART_OF = {"app.kubernetes.io/part-of": "agent-platform", "app.kubernetes.io/managed-by": "agentctl"}
#: Where the prompt lives inside its ConfigMap.
PROMPT_KEY = "instruction"
#: The CA bundle's mount point inside every pod that talks to the model.
CA_MOUNT = "/etc/agent-platform/ca"


@dataclass
class Rendered:
    """The objects of one release, grouped in files, plus what could not be expressed."""

    files: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def write(self, directory: str | Path) -> list[Path]:
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        for stale in directory.glob("*.yaml"):
            stale.unlink()
        written = []
        for name, documents in self.files.items():
            path = directory / name
            path.write_text(_dump(documents), encoding="utf-8")
            written.append(path)
        kustomization = directory / "kustomization.yaml"
        kustomization.write_text(
            _dump([{
                "apiVersion": "kustomize.config.k8s.io/v1beta1",
                "kind": "Kustomization",
                "resources": sorted(self.files),
            }]),
            encoding="utf-8",
        )
        return [*written, kustomization]


def render(factory: Any, release: Release, *, prompt_versions: dict[str, str] | None = None) -> Rendered:
    """Render every agent of ``release`` from the manifests ``factory`` can load."""
    spec = release.spec
    out = Rendered()
    released = {agent.name: agent for agent in spec.agents}
    published = _published_tools(factory, spec.tool_server.tools)

    out.files["00-tool-server.yaml"] = _tool_server(release, published)

    for entry in spec.agents:
        manifest = factory.store.load(entry.name)
        if manifest.kind != "Agent":
            raise ConfigError(
                f"'{entry.name}' is a {manifest.kind}. kagent runs agents; a workflow needs an "
                f"orchestrator (see genai-platform) or a coordinator agent in mode: byo."
            )
        version = (prompt_versions or {}).get(entry.name)
        if entry.mode == "declarative":
            documents = _declarative(release, entry, manifest, factory, published, released, version, out.warnings)
        else:
            documents = _byo(release, entry, manifest, version, released)
        out.files[f"agent-{entry.name}.yaml"] = documents

    return out


# -- declarative -------------------------------------------------------------


def _declarative(release, entry, manifest, factory, published, released, prompt_version, warnings):
    spec, ns, name = manifest.spec, release.spec.namespace, manifest.name
    if not spec.prompt.instruction:
        raise ConfigError(f"agent '{name}': spec.prompt is empty")
    _warn_unenforced(name, spec, warnings)

    tools: list[dict[str, Any]] = []
    tool_names = []
    for ref in spec.enabled_tools:
        if not spec.permissions.tools.permits(ref.ref):
            continue
        if ref.ref not in published:
            raise ConfigError(
                f"agent '{name}' uses '{ref.ref}', which the tool server '{release.spec.tool_server.name}' "
                f"does not publish (toolServer.tools: {release.spec.tool_server.tools})"
            )
        if ref.alias:
            warnings.append(f"{name}: tool alias '{ref.alias}' for {ref.ref} is ignored in declarative mode")
        tool_names.append(ref.ref)
    if tool_names:
        tools.append({
            "type": "McpServer",
            "mcpServer": {
                "apiGroup": "kagent.dev",
                "kind": "RemoteMCPServer",
                "name": release.spec.tool_server.name,
                "toolNames": tool_names,
            },
        })

    for sub in spec.enabled_sub_agents:
        if sub.mode != "tool":
            raise ConfigError(
                f"agent '{name}': sub-agent '{sub.ref}' uses mode: {sub.mode}. kagent delegates over A2A, "
                f"which is mode: tool. Use mode: tool, or deploy '{name}' with mode: byo."
            )
        if sub.ref not in released:
            raise ConfigError(
                f"agent '{name}' delegates to '{sub.ref}', which is not in the release. Add it to "
                f"spec.agents so there is something to call over A2A."
            )
        if not spec.permissions.agents.permits(sub.ref):
            continue
        tools.append({"type": "Agent", "agent": {"name": sub.ref}})

    attributes = _resource_attributes(manifest, "kagent-declarative", prompt_version)
    body: dict[str, Any] = {
        "modelConfig": f"{name}-model",
        "systemMessageFrom": {"type": "ConfigMap", "name": f"{name}-prompt", "key": PROMPT_KEY},
        "stream": True,
        "tools": tools,
        "deployment": _pod(release, env=[_env("OTEL_RESOURCE_ATTRIBUTES", attributes)]),
    }

    agent_spec: dict[str, Any] = {
        "type": "Declarative",
        "description": manifest.metadata.description or name,
        "version": manifest.metadata.version,
        "declarative": body,
    }
    skills = factory.store.resolve_skills(spec.enabled_skills).skills.values()
    if skills:
        agent_spec["skills"] = {
            "refs": [skill_image(release, skill.name, skill.version) for skill in skills],
            "insecureSkipVerify": release.spec.skills.insecure,
        }

    return [
        _model_config(release, manifest),
        _prompt_config_map(release, manifest, prompt_version),
        _object("Agent", name, ns, agent_spec, manifest, prompt_version),
    ]


def _model_config(release, manifest) -> dict[str, Any]:
    model, provider = manifest.spec.model, release.spec.model
    spec: dict[str, Any] = {
        "provider": provider.provider,
        "model": model.name,
        "apiKeySecret": provider.api_key_secret,
        "apiKeySecretKey": provider.api_key_secret_key,
    }
    if model.max_output_tokens:
        spec["gemini"] = {"maxOutputTokens": model.max_output_tokens}
    return _object("ModelConfig", f"{manifest.name}-model", release.spec.namespace, spec, manifest)


def _prompt_config_map(release, manifest, prompt_version) -> dict[str, Any]:
    obj = _object("ConfigMap", f"{manifest.name}-prompt", release.spec.namespace, None, manifest, prompt_version)
    obj["apiVersion"] = "v1"
    obj["data"] = {PROMPT_KEY: manifest.spec.prompt.instruction}
    return obj


def _warn_unenforced(name: str, spec: Any, warnings: list[str]) -> None:
    rules = [r.name for r in (*spec.guardrails.input, *spec.guardrails.output, *spec.guardrails.tools)]
    if rules:
        warnings.append(
            f"{name}: guardrails ({', '.join(rules)}) are not enforced by kagent's declarative runtime; "
            f"use mode: byo to keep them"
        )
    limits = {k: v for k, v in (("max_tool_calls", spec.policies.max_tool_calls),
                                ("max_llm_calls", spec.policies.max_llm_calls)) if v}
    if limits:
        warnings.append(f"{name}: policies {limits} are not enforced in declarative mode")
    ignored = [k for k in ("temperature", "top_p", "top_k") if getattr(spec.model, k) is not None]
    if ignored:
        warnings.append(f"{name}: kagent's Gemini ModelConfig has no {', '.join(ignored)}; the model default applies")


# -- bring your own ----------------------------------------------------------


def _byo(release: Release, entry: AgentRelease, manifest: Any, prompt_version: str | None,
         released: dict[str, AgentRelease]) -> list[dict[str, Any]]:
    if not entry.runtime:
        raise ConfigError(f"'{entry.name}' is mode: byo and needs a runtime (langgraph or langchain)")
    spec = release.spec
    endpoints = _a2a_endpoints(release, manifest, released)
    env = [
        _env("AGENT", manifest.name),
        _env("AGENT_ENV", spec.environment),
        _env("AGENT_RUNTIME", entry.runtime),
        {
            "name": spec.model.api_key_secret_key,
            "valueFrom": {"secretKeyRef": {"name": spec.model.api_key_secret, "key": spec.model.api_key_secret_key}},
        },
        # The OTLP endpoint is not set here: kagent injects it into every agent
        # pod from its own Helm values (otel.tracing). Only the identity is ours.
        _env("OTEL_RESOURCE_ATTRIBUTES", _resource_attributes(manifest, entry.runtime, prompt_version)),
    ]
    if endpoints:
        env.append(_env("AGENT_A2A_ENDPOINTS", endpoints))
    deployment = {"image": spec.host.image, "imagePullPolicy": spec.image_pull_policy, **_pod(release, env=env)}
    agent_spec = {
        "type": "BYO",
        "description": manifest.metadata.description or manifest.name,
        "version": manifest.metadata.version,
        "byo": {"deployment": deployment},
    }
    return [_object("Agent", manifest.name, spec.namespace, agent_spec, manifest, prompt_version)]


def _a2a_endpoints(release: Release, manifest: Any, released: dict[str, AgentRelease]) -> str:
    """Where a BYO coordinator finds its sub-agents: the other pods, through kagent.

    Without this the platform would build every sub-agent *inside* the
    coordinator's pod — it works, but it is one process pretending to be three.
    With it, each delegation is an A2A call routed by kagent's controller, the
    same path a declarative coordinator's ``tools[type=Agent]`` takes.
    """
    spec, ns = release.spec, release.spec.namespace
    pairs = []
    for sub in manifest.spec.enabled_sub_agents:
        if sub.ref not in released:
            raise ConfigError(
                f"agent '{manifest.name}' delegates to '{sub.ref}', which is not in the release. Add it to "
                f"spec.agents so there is something to call over A2A."
            )
        pairs.append(f"{sub.ref}={spec.a2a_gateway.rstrip('/')}/{ns}/{sub.ref}/")
    return ",".join(pairs)


# -- tool server -------------------------------------------------------------


def _tool_server(release: Release, published: list[str]) -> list[dict[str, Any]]:
    ts, ns = release.spec.tool_server, release.spec.namespace
    labels = {"app.kubernetes.io/name": ts.name, **PART_OF}
    args = ["mcp", "serve", "--host", "0.0.0.0", "--port", str(ts.port)]
    for pattern in ts.tools:
        args += ["--tools", pattern]
    return [
        {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {"name": ts.name, "namespace": ns, "labels": labels},
            "spec": {
                "replicas": 1,
                "selector": {"matchLabels": {"app.kubernetes.io/name": ts.name}},
                "template": {
                    "metadata": {"labels": labels, "annotations": {"agents.platform/tools": ",".join(published)}},
                    "spec": {
                        "containers": [{
                            "name": "mcp",
                            "image": ts.image,
                            "imagePullPolicy": release.spec.image_pull_policy,
                            "args": args,
                            "ports": [{"name": "mcp", "containerPort": ts.port}],
                            "readinessProbe": {"tcpSocket": {"port": ts.port}, "periodSeconds": 5},
                            "resources": {"requests": {"cpu": "50m", "memory": "128Mi"},
                                          "limits": {"memory": "256Mi"}},
                        }],
                    },
                },
            },
        },
        {
            "apiVersion": "v1",
            "kind": "Service",
            "metadata": {"name": ts.name, "namespace": ns, "labels": labels},
            "spec": {
                "selector": {"app.kubernetes.io/name": ts.name},
                "ports": [{"name": "mcp", "port": ts.port, "targetPort": ts.port}],
            },
        },
        {
            "apiVersion": KAGENT_API,
            "kind": "RemoteMCPServer",
            "metadata": {"name": ts.name, "namespace": ns, "labels": labels},
            "spec": {
                "description": "Tools of the agent-platform catalogue, served by agent-mcp",
                "protocol": "STREAMABLE_HTTP",
                "url": f"http://{ts.name}.{ns}:{ts.port}/mcp",
            },
        },
    ]


def _published_tools(factory: Any, patterns: list[str]) -> list[str]:
    names = sorted(factory.registries.tools.keys())
    return [n for n in names if any(fnmatch.fnmatchcase(n, p) for p in patterns)]


# -- helpers -----------------------------------------------------------------


def skill_image(release: Release, name: str, version: str) -> str:
    """Where ``make skills`` pushes a skill, and where kagent pulls it from."""
    return f"{release.spec.skills.registry}/skills/{name}:{version}"


def _resource_attributes(manifest: Any, framework: str, prompt_version: str | None) -> str:
    attributes = agent_attributes(manifest, framework)
    if prompt_version:
        attributes["prompt.version"] = prompt_version
    return ",".join(f"{key}={value}" for key, value in attributes.items() if value)


def _pod(release: Release, *, env: list[dict[str, Any]]) -> dict[str, Any]:
    pod: dict[str, Any] = {"env": list(env)}
    bundle = release.spec.trust_bundle
    if bundle:
        path = f"{CA_MOUNT}/{bundle.key}"
        pod["env"] += [_env("SSL_CERT_FILE", path), _env("REQUESTS_CA_BUNDLE", path)]
        pod["volumes"] = [{"name": "trust-bundle", "configMap": {"name": bundle.config_map}}]
        pod["volumeMounts"] = [{"name": "trust-bundle", "mountPath": CA_MOUNT, "readOnly": True}]
    return pod


def _object(kind, name, namespace, spec, manifest, prompt_version=None) -> dict[str, Any]:
    labels = {
        "agents.platform/agent": manifest.name,
        "agents.platform/version": manifest.metadata.version,
        **PART_OF,
    }
    annotations = {}
    if kind != "ModelConfig" and manifest.spec.prompt.instruction:
        annotations["agents.platform/prompt-hash"] = agent_attributes(manifest, "")["prompt.hash"]
    if prompt_version:
        annotations["agents.platform/prompt-version"] = prompt_version
    obj: dict[str, Any] = {
        "apiVersion": KAGENT_API,
        "kind": kind,
        "metadata": {"name": name, "namespace": namespace, "labels": labels},
    }
    if annotations:
        obj["metadata"]["annotations"] = annotations
    if spec is not None:
        obj["spec"] = spec
    return obj


def _env(name: str, value: str) -> dict[str, str]:
    return {"name": name, "value": value}


class _Dumper(yaml.SafeDumper):
    pass


def _str_presenter(dumper, data):
    style = "|" if "\n" in data else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style=style)


_Dumper.add_representer(str, _str_presenter)

_HEADER = "# GENERATED by `agentctl kagent render` from agents.platform/v1 manifests — do not edit.\n"


def _dump(documents: list[dict[str, Any]]) -> str:
    return _HEADER + yaml.dump_all(documents, Dumper=_Dumper, sort_keys=False, allow_unicode=True, width=100)


def load_prompt_versions(path: str | Path | None) -> dict[str, str]:
    """``{"agent": "3"}`` as written by ``agentctl mlflow prompts push``. Missing file: none."""
    if not path or not Path(path).exists():
        return {}
    return {k: str(v) for k, v in json.loads(Path(path).read_text(encoding="utf-8")).items()}
