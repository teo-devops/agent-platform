"""Locating the configuration tree and assembling the platform context."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from agent_core.config import ConfigStore
from agent_core.config.store import TOOLS_DIR
from agent_core.errors import ConfigError
from agent_core.registry import Registries
from agent_core.telemetry import configure_tracing

#: Markers that identify the root of a platform repository.
_ROOT_MARKERS = ("configs/defaults.yaml", "catalog")


def find_root(start: str | Path | None = None) -> Path:
    """Find the platform root, walking up from ``start`` (or the cwd).

    ``AGENT_PLATFORM_ROOT`` short-circuits the search, which is what deployments
    and tests use.
    """
    override = os.getenv("AGENT_PLATFORM_ROOT")
    if override:
        return Path(override).resolve()

    current = Path(start or Path.cwd()).resolve()
    for candidate in (current, *current.parents):
        if all((candidate / marker).exists() for marker in _ROOT_MARKERS):
            return candidate
    raise ConfigError(
        f"could not find a platform root above '{current}' "
        f"(expected {' and '.join(_ROOT_MARKERS)}). Set AGENT_PLATFORM_ROOT to point at it."
    )


@dataclass
class PlatformContext:
    """Everything a build needs: where configs live and what components exist."""

    store: ConfigStore
    registries: Registries

    @property
    def environment(self) -> str:
        return self.store.environment

    @property
    def root(self) -> Path:
        return self.store.root


def load_platform(
    root: str | Path | None = None,
    environment: str | None = None,
    *,
    runtime: str | None = None,
    load_env_file: bool = True,
    tracing: bool = True,
):
    """Build an :class:`~agent_runtime.factory.AgentFactory` for a repository.

    Args:
        root: Platform root. Discovered automatically when omitted.
        environment: Environment overlay to apply (defaults to ``$AGENT_ENV``).
        runtime: Force a framework for every manifest, whatever they declare.
        load_env_file: Load the repository ``.env`` before reading configuration,
            so that ``${VAR}`` references and API keys resolve.
        tracing: Configure OpenTelemetry from ``OTEL_*`` (a no-op without an
            endpoint). A host that installs its own provider first passes
            ``False`` and calls :func:`agent_core.telemetry.configure_tracing`
            afterwards, which then reuses that provider.
    """
    from .factory import AgentFactory  # imported late: factory imports this module

    resolved_root = Path(root).resolve() if root else find_root()

    if load_env_file:
        try:
            from dotenv import load_dotenv

            load_dotenv(resolved_root / ".env")
        except ImportError:  # pragma: no cover - python-dotenv is a hard dependency
            pass

    # After the .env, so OTEL_* variables written there count. A no-op unless
    # an OTLP endpoint is configured.
    if tracing:
        configure_tracing()

    store = ConfigStore(resolved_root, environment=environment)
    registries = Registries.default()

    # Tools that live in the catalogue as plain files, alongside those a
    # distribution contributes by entry point. Same registry, two origins.
    registries.tools.load_directory(resolved_root / TOOLS_DIR, source="catalog")

    return AgentFactory(PlatformContext(store=store, registries=registries), runtime=runtime)
