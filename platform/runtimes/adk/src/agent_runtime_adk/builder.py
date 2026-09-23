"""``kind: Agent`` on Google ADK.

One of the three builders this package contributes for the ``adk`` runtime. It
turns an ``AgentManifest`` into an ``LlmAgent``; the manifest it reads is the
same one LangGraph and LangChain read, which is the whole point of keeping the
schema out of here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from agent_core.errors import BuildError, PermissionDeniedError, PlatformError
from agent_core.result import BuildResult
from agent_core.schemas import AgentManifest
from agent_core.telemetry import agent_attributes, get_logger, log_event
from google.adk.agents import LlmAgent
from google.adk.tools import FunctionTool
from google.adk.tools.agent_tool import AgentTool

from .model import resolve_model
from .plugins import build_plugins
from .tools import build_tools

if TYPE_CHECKING:  # pragma: no cover
    from agent_runtime.factory import AgentFactory

logger = get_logger("adk.builder")


class AgentBuilder:
    """Builds a single LLM agent, recursing into the sub-agents it declares."""

    kind = "Agent"
    runtime = "adk"

    def build(self, manifest: AgentManifest, factory: "AgentFactory") -> BuildResult:
        spec = manifest.spec
        name = manifest.metadata.python_name
        model_name, generate_config = resolve_model(spec.model)

        if not spec.prompt.instruction:
            raise BuildError(
                f"agent '{manifest.name}': spec.prompt.instruction is empty. "
                f"Set it inline or point prompt.file at a prompt file."
            )

        resolved_tools = build_tools(spec.enabled_tools, factory.registries.tools, spec.permissions, agent=name)
        tools: list[Any] = list(resolved_tools.tools)

        # Skills: sólo el índice viaja en el prompt; el cuerpo lo sirven estas
        # dos herramientas cuando el agente decide que lo necesita.
        skills = factory.store.resolve_skills(spec.enabled_skills)
        instruction = spec.prompt.instruction + skills.prompt_section()
        for ref, funcion in skills.as_tools().items():
            tools.append(FunctionTool(func=funcion))
        aliases = dict(resolved_tools.aliases)
        agent_aliases: dict[str, str] = {}
        sub_agents: list[Any] = []
        plugins: list[Any] = []

        for ref in spec.enabled_sub_agents:
            if not spec.permissions.agents.permits(ref.ref):
                raise PermissionDeniedError(
                    f"agent '{manifest.name}' declares sub-agent '{ref.ref}', "
                    f"which its permissions.agents rules do not allow"
                )
            remote = factory.remote(ref.ref)
            if remote is not None:
                if ref.mode != "tool":
                    raise BuildError(
                        f"agent '{manifest.name}': sub-agent '{ref.ref}' runs in another process "
                        f"({remote.url}); only mode 'tool' can cross a process boundary."
                    )
                tool = FunctionTool(func=_remote_tool(remote, ref))
                tools.append(tool)
                agent_aliases[tool.name] = ref.ref
                continue

            child = factory.build(ref.ref)
            plugins.extend(child.plugins)

            if ref.mode == "tool":
                tool = AgentTool(agent=child.agent)
                if ref.description:
                    tool.description = ref.description
                tools.append(tool)
                agent_aliases[tool.name] = ref.ref
            else:
                sub_agents.append(child.agent)

        agent = LlmAgent(
            name=name,
            model=model_name,
            description=manifest.metadata.description,
            instruction=instruction,
            global_instruction=spec.prompt.global_instruction or "",
            tools=tools,
            sub_agents=sub_agents,
            output_key=spec.output_key,
            **({"generate_content_config": generate_config} if generate_config else {}),
        )

        plugins = build_plugins(
            agent=name,
            guardrails=spec.guardrails,
            policies=spec.policies,
            permissions=spec.permissions,
            extra=spec.plugins,
            registry=factory.registries.plugins,
            tool_aliases=aliases,
            agent_aliases=agent_aliases,
            audit=factory.audit,
            attributes=agent_attributes(manifest, "adk"),
        ) + plugins

        log_event(
            logger,
            "agent built",
            agent=manifest.name,
            model=model_name,
            tools=len(tools),
            skills=sorted(skills.skills) or None,
            sub_agents=len(sub_agents),
            denied_tools=resolved_tools.denied or None,
            plugins=[p.name for p in plugins],
        )
        return BuildResult(agent=agent, plugins=plugins, manifest=manifest)


def _remote_tool(remote: Any, ref: Any) -> Any:
    """A sub-agent in another process, as an ADK function tool.

    Named like the ``AgentTool`` it replaces, so the coordinator's prompt, its
    permissions and its traces read the same whichever side of the wire the
    child is on.
    """

    async def call(request: str) -> str:
        try:
            return await remote.acall(request)
        except PlatformError as exc:  # the coordinator reads it and decides; no crash
            return f"ERROR: {exc}"

    call.__name__ = ref.ref.replace("-", "_")
    call.__doc__ = (
        f"{ref.description or f'Delegate the request to the {ref.ref!r} agent.'}\n\n"
        f"Args:\n    request: What the agent has to do, in plain words."
    )
    return call
