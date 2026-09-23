"""``kind: Agent`` on LangChain.

The same manifest again. Here it becomes a ``create_agent`` from LangChain 1.x,
with the declared enforcement supplied as middleware.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from agent_core.errors import BuildError, PermissionDeniedError, PlatformError
from agent_core.result import BuildResult
from agent_core.schemas import AgentManifest
from agent_core.telemetry import get_logger, log_event
from langchain_core.tools import StructuredTool

from .enforcement import build_middleware
from .model import resolve_model
from .tools import build_tools

if TYPE_CHECKING:  # pragma: no cover
    from agent_runtime.factory import AgentFactory

logger = get_logger("langchain.builder")


class AgentBuilder:
    """Builds one agent, recursing into the sub-agents it declares."""

    kind = "Agent"
    runtime = "langchain"

    def build(self, manifest: AgentManifest, factory: "AgentFactory") -> BuildResult:
        from langchain.agents import create_agent

        spec = manifest.spec
        name = manifest.metadata.python_name

        if not spec.prompt.instruction:
            raise BuildError(
                f"agent '{manifest.name}': spec.prompt.instruction is empty. "
                f"Set it inline or point prompt.file at a prompt file."
            )

        resolved = build_tools(
            spec.enabled_tools, factory.registries.tools, spec.permissions, agent=name
        )
        tools: list[Any] = list(resolved.tools)

        # Skills: sólo el índice viaja en el prompt; el cuerpo lo sirven estas
        # dos herramientas cuando el agente decide que lo necesita.
        skills = factory.store.resolve_skills(spec.enabled_skills)
        instruction = spec.prompt.instruction + skills.prompt_section()
        for ref, funcion in skills.as_tools().items():
            tools.append(
                StructuredTool.from_function(
                    func=funcion, name=ref.replace(".", "_"), description=funcion.__doc__
                )
            )
        aliases = dict(resolved.aliases)
        plugins: list[Any] = []

        for ref in spec.enabled_sub_agents:
            if not spec.permissions.agents.permits(ref.ref):
                raise PermissionDeniedError(
                    f"agent '{manifest.name}' declares sub-agent '{ref.ref}', "
                    f"which its permissions.agents rules do not allow"
                )
            if ref.mode != "tool":
                raise BuildError(
                    f"agent '{manifest.name}': sub-agent '{ref.ref}' uses mode "
                    f"'{ref.mode}'. Handing the turn over to another agent is an ADK "
                    f"construct with no LangChain equivalent. Use mode 'tool', or run "
                    f"this agent on the adk runtime."
                )
            remote = factory.remote(ref.ref)
            if remote is not None:
                tool = _remote_as_tool(remote, ref)
            else:
                child = factory.build(ref.ref)
                plugins.extend(child.plugins)
                tool = _as_tool(child, ref)
            tools.append(tool)
            aliases[tool.name] = ref.ref

        middleware = build_middleware(
            agent=name,
            guardrails=spec.guardrails,
            policies=spec.policies,
            permissions=spec.permissions,
            aliases=aliases,
        )

        agent = create_agent(
            model=resolve_model(spec.model),
            tools=tools,
            system_prompt=instruction,
            middleware=[middleware],
            name=name,
        )

        log_event(
            logger,
            "agent built",
            agent=manifest.name,
            runtime="langchain",
            tools=len(tools),
            skills=sorted(skills.skills) or None,
            denied_tools=resolved.denied or None,
        )
        return BuildResult(agent=agent, plugins=[middleware, *plugins], manifest=manifest)


def _as_tool(child: BuildResult, ref: Any) -> Any:
    """Expose a built sub-agent as a tool of its coordinator."""
    from langchain_core.tools import StructuredTool

    def call(request: str) -> str:
        """Delegate to another agent and return its answer."""
        answer = child.agent.invoke({"messages": [{"role": "user", "content": request}]})
        messages = answer.get("messages", [])
        return messages[-1].text if messages else ""

    return StructuredTool.from_function(
        func=call,
        name=(ref.alias or ref.ref).replace("-", "_"),
        description=ref.description or f"Delegate the request to the '{ref.ref}' agent.",
    )


def _remote_as_tool(remote: Any, ref: Any) -> Any:
    """A sub-agent in another process, as a tool: same name, same description.

    The coordinator cannot tell it apart from :func:`_as_tool` — which is the
    point: where the child runs is the deployment's business, not the prompt's.
    """
    from langchain_core.tools import StructuredTool

    def call(request: str) -> str:
        """Delegate to another agent and return its answer."""
        try:
            return remote(request)
        except PlatformError as exc:  # the coordinator reads it and decides; no crash
            return f"ERROR: {exc}"

    async def acall(request: str) -> str:
        """Delegate to another agent and return its answer."""
        try:
            return await remote.acall(request)
        except PlatformError as exc:
            return f"ERROR: {exc}"

    return StructuredTool.from_function(
        func=call,
        coroutine=acall,
        name=(ref.alias or ref.ref).replace("-", "_"),
        description=ref.description or f"Delegate the request to the '{ref.ref}' agent.",
    )
