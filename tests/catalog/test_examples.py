"""Los ejemplos nativos se construyen de verdad.

Un ejemplo que ya no compila es peor que no tener ejemplo: enseña una API que
cambió. Esto los importa y los construye todos —sin llamar a ningún modelo— para
que envejezcan en rojo y no en silencio.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "examples"

RUNTIME_DE = {"en_adk": "adk", "en_langgraph": "langgraph", "en_langchain": "langchain"}


def _instalados() -> set[str]:
    from agent_core.registry import Registries

    return set(Registries.default().runtimes.keys())


INSTALADOS = _instalados()
EJEMPLOS = sorted(EXAMPLES.glob("*/en_*.py"))


def _id(ruta: Path) -> str:
    return f"{ruta.parent.name}/{ruta.stem}"


@pytest.fixture(autouse=True)
def _credencial_ficticia(monkeypatch):
    """Construir no llama al modelo, pero los clientes quieren una clave."""
    monkeypatch.setenv("GEMINI_API_KEY", os.environ.get("GEMINI_API_KEY", "test-key-not-used"))
    monkeypatch.setenv("GOOGLE_API_KEY", os.environ.get("GOOGLE_API_KEY", "test-key-not-used"))


def test_the_ladder_is_complete():
    """Cada escalón, en los tres frameworks. Si falta uno, la escalera cojea."""
    escalones = sorted(p.name for p in EXAMPLES.iterdir() if p.is_dir())
    assert escalones, "no hay ejemplos"

    for escalon in escalones:
        for modulo in RUNTIME_DE:
            ruta = EXAMPLES / escalon / f"{modulo}.py"
            assert ruta.exists(), f"falta {ruta.relative_to(ROOT)}"
        assert (EXAMPLES / escalon / "README.md").exists(), f"{escalon} no explica nada"


@pytest.mark.parametrize("ruta", EJEMPLOS, ids=_id)
def test_example_builds(ruta: Path):
    runtime = RUNTIME_DE[ruta.stem]
    if runtime not in INSTALADOS:
        pytest.skip(f"el runtime '{runtime}' no está instalado")

    spec = importlib.util.spec_from_file_location(f"ejemplo_{ruta.parent.name}_{ruta.stem}", ruta)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)

    assert hasattr(modulo, "construir"), f"{_id(ruta)} no expone construir()"
    assert modulo.construir() is not None


@pytest.mark.parametrize("ruta", EJEMPLOS, ids=_id)
def test_example_does_not_use_the_platform(ruta: Path):
    """El valor del ejemplo nativo es que NO usa la plataforma.

    En cuanto uno importa `agent_runtime`, deja de enseñar el framework y pasa a
    enseñar esto — que ya está enseñado en los manifiestos.
    """
    codigo = ruta.read_text(encoding="utf-8")
    for prohibido in ("agent_runtime", "agent_core", "agent_mcp", "agent_kagent", "agent_mlflow"):
        assert prohibido not in codigo, f"{_id(ruta)} importa '{prohibido}'"
