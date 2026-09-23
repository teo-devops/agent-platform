"""Component registries and entry-point discovery."""

from __future__ import annotations

import pytest
from agent_core.errors import RegistryError
from agent_core.registry import Registry


def test_register_and_resolve():
    registry: Registry[object] = Registry("test")
    registry.register("a.b", 42)
    assert registry.get("a.b") == 42
    assert registry.match("a.*") == ["a.b"]


def test_duplicate_registration_is_rejected_unless_overridden():
    registry: Registry[object] = Registry("test")
    registry.register("a", 1)
    with pytest.raises(RegistryError, match="already registered"):
        registry.register("a", 2)
    registry.register("a", 2, override=True)
    assert registry.get("a") == 2


def test_unknown_reference_lists_the_alternatives():
    registry: Registry[object] = Registry("test")
    registry.register("known", 1)
    with pytest.raises(RegistryError, match="known"):
        registry.get("unknown")


def test_the_catalogue_publishes_its_tools(registries):
    """Una tool es un fichero de `catalog/tools/`, no un entry point.

    Soltar un `.py` ahí la publica como `<fichero>.<funcion>`: ni paquete que
    tocar, ni reinstalar. Lo que sí sigue llegando por entry point son los
    plugins, que son código de plataforma y no contenido.
    """
    assert "health.calculate_bmi" in registries.tools.keys()
    assert callable(registries.tools.get("health.calculate_bmi"))
    assert registries.tools.component("health.calculate_bmi").source.startswith("catalog:")

    # Lo privado y lo importado de otro módulo no se publica.
    assert not [ref for ref in registries.tools.keys() if ref.split(".")[-1].startswith("_")]


def test_installed_packages_contribute_their_components(registries):
    assert "guardrails" in registries.plugins.keys()

    # Builders are keyed "<kind>:<runtime>", so two frameworks can each offer a
    # builder for the same kind. Installing a runtime package is what makes its
    # builders appear; nothing imports them by name.
    installed = set(registries.runtimes.keys())
    assert installed, "no runtime installed: manifests would not be executable"

    builders = set(registries.builders.keys())
    for runtime in installed:
        assert {f"agent:{runtime}", f"workflow:{runtime}"} <= builders, (
            f"runtime '{runtime}' does not cover both manifest kinds"
        )

