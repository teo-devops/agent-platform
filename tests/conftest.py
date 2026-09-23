"""Shared fixtures. Tests run against the repository's real configuration tree."""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def root() -> Path:
    return ROOT


@pytest.fixture
def store():
    from agent_core.config import ConfigStore

    return ConfigStore(ROOT, environment="local")


@pytest.fixture
def factory():
    from agent_runtime import load_platform

    return load_platform(root=ROOT, environment="local", load_env_file=False)


@pytest.fixture
def registries():
    """Registries con las tools del catálogo ya cargadas.

    Las tools dejaron de ser entry points de un paquete y pasaron a ser ficheros
    de `catalog/tools/`, así que ahora hay que decir de dónde salen — igual que
    hace `load_platform` al montar la plataforma.
    """
    from agent_core.config import TOOLS_DIR
    from agent_core.registry import Registries

    found = Registries.default()
    found.tools.load_directory(ROOT / TOOLS_DIR, source="catalog")
    return found
