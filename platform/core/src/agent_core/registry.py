"""Component registries with entry-point discovery.

A registry maps a stable *reference* (``"health.calculate_bmi"``) to a Python
object. References are what configuration files use, so a config never imports
Python: it names a component and the platform resolves it.

Components can be contributed in two ways:

1. **Entry points** -- the packaged, versioned way. A distribution declares
   ``[project.entry-points."agent_platform.tools"]`` and its tools become
   available to every agent as soon as the distribution is installed.
2. **Explicit registration** -- ``registry.register(ref, obj)``, useful for
   tests and for project-local components.
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field
from importlib.metadata import EntryPoint, entry_points
from pathlib import Path
from typing import Any, Generic, Iterator, TypeVar

from .errors import RegistryError

T = TypeVar("T")

#: Entry-point group for callables exposed to agents as tools.
TOOLS_GROUP = "agent_platform.tools"
#: Entry-point group for runtime plugin classes (guardrails, audit, policy...).
PLUGINS_GROUP = "agent_platform.plugins"
#: Entry-point group for builders that turn a manifest ``kind`` into an agent.
#: Keys are ``"<kind>:<runtime>"`` (``agent:adk``), with a bare ``"<kind>"``
#: still accepted so that a builder written before runtimes existed keeps working.
BUILDERS_GROUP = "agent_platform.builders"
#: Entry-point group for whole frameworks: build, wrap and run. One per runtime.
RUNTIMES_GROUP = "agent_platform.runtimes"
#: Entry-point group for ``agentctl`` subcommands contributed by other packages
#: (``deploy``, ``mcp``, ``mlflow``...). Each entry is ``register(subparsers)``.
COMMANDS_GROUP = "agent_platform.commands"
#: Entry-point group for eval result sinks: ``publish(result, context)``.
EVAL_SINKS_GROUP = "agent_platform.eval_sinks"
#: Entry-point group for the ways of reaching an agent that runs in another
#: process (``a2a``). Each entry is ``factory(name=..., url=...)`` and returns a
#: delegate: callable with the request text, plus an async ``acall``.
TRANSPORTS_GROUP = "agent_platform.transports"


@dataclass(frozen=True)
class Component(Generic[T]):
    """A registered component together with its provenance."""

    ref: str
    obj: T
    source: str = "inline"
    metadata: dict[str, Any] = field(default_factory=dict)


class Registry(Generic[T]):
    """A namespaced, lazily-populated registry of components."""

    def __init__(self, name: str, entry_point_group: str | None = None) -> None:
        self.name = name
        self.entry_point_group = entry_point_group
        self._items: dict[str, Component[T]] = {}
        self._pending: dict[str, EntryPoint] = {}
        self._discovered = False

    # -- population ---------------------------------------------------------

    def register(self, ref: str, obj: T, *, source: str = "inline", override: bool = False,
                 metadata: dict[str, Any] | None = None) -> None:
        """Register ``obj`` under ``ref``.

        Raises:
            RegistryError: if ``ref`` is already taken and ``override`` is False.
        """
        if ref in self._items and not override:
            raise RegistryError(
                f"{self.name}: reference '{ref}' is already registered by "
                f"'{self._items[ref].source}'. Pass override=True to replace it."
            )
        self._items[ref] = Component(ref=ref, obj=obj, source=source, metadata=metadata or {})

    def discover(self, *, force: bool = False) -> None:
        """Index the entry points of the configured group (without importing them)."""
        if self.entry_point_group is None or (self._discovered and not force):
            return
        for ep in entry_points(group=self.entry_point_group):
            if ep.name not in self._items:
                self._pending[ep.name] = ep
        self._discovered = True

    def load_directory(self, directory: Path, *, source: str = "directory") -> list[str]:
        """Register every public function of every module in ``directory``.

        This is what makes a tool *content* instead of library code. Dropping a
        ``.py`` file into ``catalog/tools/`` publishes its functions as
        ``<fichero>.<funcion>`` — no package to edit, no entry point to declare,
        no reinstall. A published distribution can still contribute tools through
        entry points; both end up in this same registry.
        """
        import importlib.util
        import inspect

        directory = Path(directory)
        if not directory.exists():
            return []

        registered: list[str] = []
        for module_path in sorted(directory.glob("*.py")):
            if module_path.stem.startswith("_"):
                continue

            spec = importlib.util.spec_from_file_location(
                f"_catalog_tools_{module_path.stem}", module_path
            )
            if spec is None or spec.loader is None:  # pragma: no cover - unreadable file
                continue
            module = importlib.util.module_from_spec(spec)
            try:
                spec.loader.exec_module(module)
            except Exception as exc:
                raise RegistryError(f"{self.name}: failed to load '{module_path}': {exc}") from exc

            exported = getattr(module, "__all__", None)
            for function_name, function in vars(module).items():
                if function_name.startswith("_") or not inspect.isfunction(function):
                    continue
                if function.__module__ != module.__name__:  # imported, not defined here
                    continue
                if exported is not None and function_name not in exported:
                    continue

                ref = f"{module_path.stem}.{function_name}"
                self.register(ref, function, source=f"{source}:{module_path}", override=True)
                registered.append(ref)

        return registered

    # -- lookup -------------------------------------------------------------

    def get(self, ref: str) -> T:
        """Resolve ``ref``, importing its entry point on first use."""
        self.discover()
        if ref in self._items:
            return self._items[ref].obj
        if ref in self._pending:
            ep = self._pending.pop(ref)
            try:
                obj = ep.load()
            except Exception as exc:  # pragma: no cover - depends on third-party code
                raise RegistryError(f"{self.name}: failed to load '{ref}' from '{ep.value}': {exc}") from exc
            self.register(ref, obj, source=f"entry-point:{ep.value}")
            return obj
        raise RegistryError(
            f"{self.name}: unknown reference '{ref}'. Available: {', '.join(sorted(self.keys())) or '<none>'}"
        )

    def component(self, ref: str) -> Component[T]:
        """Like :meth:`get` but returns the component wrapper with its provenance."""
        self.get(ref)
        return self._items[ref]

    def keys(self) -> list[str]:
        """All known references, resolved or still pending import."""
        self.discover()
        return sorted({*self._items, *self._pending})

    def match(self, pattern: str) -> list[str]:
        """References matching a glob pattern such as ``"health.*"``."""
        return [ref for ref in self.keys() if fnmatch.fnmatch(ref, pattern)]

    def __contains__(self, ref: object) -> bool:
        return isinstance(ref, str) and ref in self.keys()

    def __iter__(self) -> Iterator[str]:
        return iter(self.keys())

    def __len__(self) -> int:
        return len(self.keys())

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Registry {self.name} items={len(self)}>"


@dataclass
class Registries:
    """The set of registries a build needs, passed around as one object."""

    tools: Registry[Any] = field(default_factory=lambda: Registry("tools", TOOLS_GROUP))
    plugins: Registry[Any] = field(default_factory=lambda: Registry("plugins", PLUGINS_GROUP))
    builders: Registry[Any] = field(default_factory=lambda: Registry("builders", BUILDERS_GROUP))
    runtimes: Registry[Any] = field(default_factory=lambda: Registry("runtimes", RUNTIMES_GROUP))
    transports: Registry[Any] = field(default_factory=lambda: Registry("transports", TRANSPORTS_GROUP))

    @classmethod
    def default(cls) -> "Registries":
        """Registries wired to the standard entry-point groups."""
        return cls()
