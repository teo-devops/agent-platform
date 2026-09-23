"""The entry point of the runtime: manifests in, runnable objects out.

This module used to return a `google.adk.apps.App` by name. That single typed
import was what made "run an agent" mean "run an ADK agent": nothing else could
be plugged in, however neutral the rest of the platform claimed to be.

Now it resolves a :class:`~agent_core.contracts.Runtime` and delegates. Which
framework answers is a line of YAML.
"""

from __future__ import annotations

from typing import Any

from agent_core.errors import BuildError, ConfigError
from agent_core.registry import Registries
from agent_core.result import BuildResult
from agent_core.telemetry import get_logger

from .context import PlatformContext

logger = get_logger("runtime.factory")


class AgentFactory:
    """Builds agents and apps from the declarative configuration of a repository."""

    def __init__(
        self,
        context: PlatformContext,
        *,
        audit: bool = True,
        runtime: str | None = None,
    ) -> None:
        self.context = context
        self.audit = audit
        #: Overrides whatever the manifests say. Set from ``agentctl --runtime``.
        self.runtime_override = runtime
        self._stack: list[str] = []

    # -- convenience accessors ---------------------------------------------

    @property
    def store(self):
        return self.context.store

    @property
    def registries(self) -> Registries:
        return self.context.registries

    @property
    def environment(self) -> str:
        return self.context.environment

    # -- building -----------------------------------------------------------

    def build(self, name: str) -> BuildResult:
        """Build ``name`` (agent or workflow) with its plugin stack."""
        if name in self._stack:
            cycle = " -> ".join([*self._stack, name])
            raise BuildError(f"circular reference between agents: {cycle}")

        manifest = self.store.load(name)
        runtime = self.runtime_name(manifest)
        builder = self._builder_for(manifest.kind, runtime)

        self._stack.append(name)
        try:
            result = builder.build(manifest, self)
        finally:
            self._stack.pop()

        if not isinstance(result, BuildResult):  # a builder returned a bare agent
            result = BuildResult(agent=result, manifest=manifest)
        return result

    def build_agent(self, name: str) -> Any:
        """Build just the agent object, discarding the plugin stack.

        Useful for embedding an agent in another runtime; prefer
        :meth:`build_app` when you intend to run it, so guardrails, permissions
        and policy are actually enforced.
        """
        return self.build(name).agent

    def build_app(self, name: str) -> Any:
        """Build a runnable application, in whatever shape the runtime uses."""
        result = self.build(name)
        return self.runtime(self.runtime_name(result.manifest)).app(result)

    def validate(self, name: str) -> list[str]:
        """Build ``name`` without running it and report problems as messages."""
        try:
            self.build(name)
        except (ConfigError, BuildError) as exc:
            return [str(exc)]
        except Exception as exc:  # noqa: BLE001 - report anything the build raises
            return [f"{type(exc).__name__}: {exc}"]
        return []

    def remote(self, name: str) -> Any | None:
        """How to reach ``name`` if the environment runs it in another process.

        Builders ask before building a sub-agent: ``None`` means "build it here",
        anything else is a delegate — call it with the request text (or await
        its ``acall``) and it answers over the wire. The manifest that declared
        the sub-agent does not change either way.
        """
        url = self.store.remote_agents.get(name)
        if not url:
            return None
        try:
            transport = self.registries.transports.get("a2a")
        except Exception:
            raise BuildError(
                f"'{name}' is configured as remote ({url}) but no A2A transport is installed. "
                f"Install it with 'pip install -e platform/a2a'."
            ) from None
        return transport(name=name, url=url)

    def participants(self, name: str) -> tuple[dict[str, str], dict[str, str]]:
        """Who can show up when ``name`` runs, by the names the frameworks use.

        Returns ``(agents, delegates)``: agents indexed by catalogue *and*
        Python name (and workflow steps by their step name), and the tool names
        under which a coordinator sees each sub-agent. What
        :func:`agent_core.telemetry.enable_narration` needs to tell a delegation
        apart from an ordinary tool call.
        """
        agents: dict[str, str] = {}
        delegates: dict[str, str] = {}
        pending, seen = [name], set()
        while pending:
            current = pending.pop()
            if current in seen:
                continue
            seen.add(current)
            manifest = self.store.load(current)
            agents[current] = agents[current.replace("-", "_")] = current
            for node in getattr(manifest.spec, "nodes", None) or []:
                # A workflow step is traced under the step's name, not the agent's.
                agents[node.name] = agents[node.name.replace("-", "_")] = node.agent
                pending.append(node.agent)
            for ref in getattr(manifest.spec, "enabled_sub_agents", []):
                for tool_name in {ref.ref, ref.alias or ref.ref}:
                    delegates[tool_name.replace("-", "_")] = ref.ref
                pending.append(ref.ref)
        return agents, delegates

    # -- runtimes -----------------------------------------------------------

    def runtime_name(self, manifest: Any = None) -> str:
        """Which framework runs this manifest.

        The command line wins over the manifest, and the manifest wins over the
        fleet default — the same precedence every other setting follows.
        """
        if self.runtime_override:
            return self.runtime_override

        declared = getattr(getattr(manifest, "spec", None), "runtime", None)
        if declared:
            return declared

        installed = self.registries.runtimes.keys()
        if len(installed) == 1:
            return installed[0]

        raise ConfigError(
            f"no runtime declared and {len(installed)} installed "
            f"({', '.join(installed) or 'none'}). Set spec.runtime in the manifest, "
            f"agentDefaults.runtime in configs/defaults.yaml, or pass --runtime."
        )

    def runtime(self, name: str) -> Any:
        """Resolve an installed runtime by name."""
        try:
            resolved = self.registries.runtimes.get(name)
        except Exception:
            raise BuildError(
                f"runtime '{name}' is not installed. Available: "
                f"{', '.join(self.registries.runtimes.keys()) or 'none'}. "
                f"Install it with 'pip install -e platform/runtimes/{name}'."
            ) from None
        return resolved() if isinstance(resolved, type) else resolved

    # -- internals ----------------------------------------------------------

    def _builder_for(self, kind: str, runtime: str) -> Any:
        """Resolve the builder for a manifest kind on a given framework.

        Keyed ``"<kind>:<runtime>"``, falling back to a bare ``"<kind>"`` so a
        builder written before runtimes existed still resolves.
        """
        for key in (f"{kind.lower()}:{runtime}", kind.lower()):
            try:
                factory = self.registries.builders.get(key)
            except Exception:
                continue
            return factory() if isinstance(factory, type) else factory

        raise BuildError(
            f"no builder registered for kind '{kind}' on runtime '{runtime}'. "
            f"Install the package that provides it: "
            f"'pip install -e platform/runtimes/{runtime}'. "
            f"Registered: {', '.join(self.registries.builders.keys()) or 'none'}."
        )
