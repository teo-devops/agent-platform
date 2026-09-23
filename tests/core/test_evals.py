"""Las evals: que la maquinaria mida lo que dice medir.

Aquí no se llama a ningún modelo. Lo que se comprueba es el motor —aserciones,
umbral, lectura de las suites— y que las suites del repositorio sean válidas.
Puntuar de verdad a un agente exige ejecutarlo, y eso vive en `agentctl eval`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SUITES = sorted(p.parent.name for p in ROOT.glob("evals/*/dataset.yaml"))


@pytest.mark.parametrize("name", SUITES)
def test_every_suite_loads_and_targets_something_real(store, name):
    from agent_core.evals import load_suite

    suite, criteria = load_suite(ROOT / "evals" / name)
    conocidos = [*store.list_agents(), *store.list_workflows()]
    assert suite.spec.target in conocidos, (
        f"la suite '{name}' evalúa '{suite.spec.target}', que no existe"
    )
    assert suite.spec.cases, "una suite sin casos no mide nada"

    ids = [case.id for case in suite.spec.cases]
    assert len(ids) == len(set(ids)), f"ids repetidos en '{name}': {ids}"


@pytest.mark.parametrize("name", SUITES)
def test_cases_actually_assert_something(name):
    """Un caso sin aserciones ni juez pasa siempre. Verde y sin medir nada."""
    from agent_core.evals import load_suite

    suite, _ = load_suite(ROOT / "evals" / name)
    for case in suite.spec.cases:
        assert not (case.expect.is_empty and not case.judge), (
            f"el caso '{name}/{case.id}' no comprueba nada: pasaría siempre"
        )


def test_unknown_judge_criteria_are_rejected(tmp_path):
    """Un criterio que no existe dejaría el caso sin evaluar, en silencio."""
    from agent_core.errors import ConfigError
    from agent_core.evals import load_suite

    (tmp_path / "dataset.yaml").write_text(
        "apiVersion: agents.platform/v1\n"
        "kind: EvalSuite\n"
        "metadata: {name: x}\n"
        "spec:\n"
        "  target: greeting\n"
        "  cases:\n"
        "    - id: uno\n"
        "      input: hola\n"
        "      judge: [no-existe]\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="no existen"):
        load_suite(tmp_path)


@pytest.mark.parametrize(
    "output, expect, esperados",
    [
        ("El IMC es 24.2", {"contains": ["24.2"]}, 0),
        ("El IMC es 25.0", {"contains": ["24.2"]}, 1),
        ("todo bien", {"not_contains": ["mal"]}, 0),
        ("está mal", {"not_contains": ["mal"]}, 1),
        ("x" * 50, {"max_chars": 10}, 1),
        ("x", {"min_chars": 10}, 1),
        ('{"a": 1}', {"json_valid": True}, 0),
        ("no json", {"json_valid": True}, 1),
        ("abc123", {"matches": r"\d+"}, 0),
        ("abc", {"matches": r"\d+"}, 1),
    ],
)
def test_deterministic_assertions(output, expect, esperados):
    from agent_core.evals import Assertion, evaluate_assertions

    assert len(evaluate_assertions(output, Assertion(**expect))) == esperados


@pytest.mark.asyncio
async def test_the_score_is_the_fraction_that_passes():
    from agent_core.evals import load_suite, run_suite

    suite, criteria = load_suite(ROOT / "evals" / "health-advisor")

    async def siempre_correcto(entrada: str) -> str:
        # Satisface los `contains` de las dos primeras y evita los `not_contains`.
        return "Tu IMC es 24.2 y también 14.7, en rango saludable."

    resultado = await run_suite(suite, criteria, run=siempre_correcto, judge=None)
    assert resultado.score == 1.0
    assert resultado.meets_threshold

    async def siempre_mal(entrada: str) -> str:
        return "inf"

    peor = await run_suite(suite, criteria, run=siempre_mal, judge=None)
    assert peor.score < suite.spec.threshold
    assert not peor.meets_threshold


@pytest.mark.asyncio
async def test_a_judge_that_cannot_be_read_fails_the_case():
    """Ante la duda, suspende.

    Dar por bueno lo que no se pudo leer convierte la suite en decorado: pasaría
    igual con un juez roto que con un agente perfecto.
    """
    from agent_core.evals import load_suite, run_suite

    suite, criteria = load_suite(ROOT / "evals" / "greeting")

    async def responde(entrada: str) -> str:
        return "Hola, qué tal."

    async def juez_ilegible(peticion: str) -> str:
        return "pues depende, la verdad"

    resultado = await run_suite(suite, criteria, run=responde, judge=juez_ilegible)
    juzgados = [c for c in resultado.cases if c.case.judge]
    assert juzgados and all(not c.passed for c in juzgados)


@pytest.mark.asyncio
async def test_a_case_that_blows_up_is_a_failure_not_a_crash():
    from agent_core.evals import load_suite, run_suite

    suite, criteria = load_suite(ROOT / "evals" / "greeting")

    async def revienta(entrada: str) -> str:
        raise RuntimeError("el proveedor se ha caído")

    resultado = await run_suite(suite, criteria, run=revienta, judge=None)
    assert resultado.score == 0.0
    assert all("RuntimeError" in (c.error or "") for c in resultado.cases)
