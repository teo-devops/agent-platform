"""Ejecutar una suite y devolver un número comparable."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable

import yaml

from ..errors import ConfigError
from .schemas import Assertion, Criterion, EvalCase, EvalSuite

#: Nombre del agente del catálogo que hace de juez.
JUDGE_AGENT = "eval-judge"

DATASET_FILE = "dataset.yaml"
JUDGES_FILE = "judges.yaml"


@dataclass
class CaseResult:
    """Qué pasó con un caso."""

    case: EvalCase
    output: str = ""
    failures: list[str] = field(default_factory=list)
    judged: dict[str, bool] = field(default_factory=dict)
    error: str | None = None
    #: Traza de la ejecución del objetivo, si había tracing. La rellena quien
    #: ejecuta, no el motor: aquí no se sabe nada de OpenTelemetry.
    trace_id: str | None = None

    @property
    def passed(self) -> bool:
        return not self.failures and self.error is None


@dataclass
class SuiteResult:
    """Qué pasó con la suite entera."""

    suite: EvalSuite
    cases: list[CaseResult] = field(default_factory=list)
    judged: bool = True

    @property
    def score(self) -> float:
        if not self.cases:
            return 0.0
        return sum(1 for case in self.cases if case.passed) / len(self.cases)

    @property
    def meets_threshold(self) -> bool:
        umbral = self.suite.spec.threshold
        return self.score >= umbral if self.suite.spec.goal == "maximize" else self.score <= umbral


def load_suite(directory: Path) -> tuple[EvalSuite, dict[str, Criterion]]:
    """Leer ``dataset.yaml`` y ``judges.yaml`` de una suite."""
    directory = Path(directory)
    dataset = directory / DATASET_FILE
    if not dataset.exists():
        raise ConfigError(f"{directory} no es una suite: falta {DATASET_FILE}")

    suite = EvalSuite.model_validate(yaml.safe_load(dataset.read_text(encoding="utf-8")))

    criterios: dict[str, Criterion] = {}
    judges = directory / JUDGES_FILE
    if judges.exists():
        crudo = yaml.safe_load(judges.read_text(encoding="utf-8")) or {}
        criterios = {
            nombre: Criterion.model_validate(cuerpo)
            for nombre, cuerpo in (crudo.get("criteria") or {}).items()
        }

    # Un caso que invoca un criterio inexistente pasaría silenciosamente sin
    # evaluarse, que es la peor forma de fallar: verde y sin medir nada.
    for caso in suite.spec.cases:
        desconocidos = [c for c in caso.judge if c not in criterios]
        if desconocidos:
            raise ConfigError(
                f"{dataset}: el caso '{caso.id}' usa criterios que no existen en "
                f"{JUDGES_FILE}: {', '.join(desconocidos)}"
            )

    return suite, criterios


def evaluate_assertions(output: str, expect: Assertion) -> list[str]:
    """Comprobaciones deterministas. Devuelve la lista de fallos."""
    fallos: list[str] = []

    for esperado in expect.contains:
        if esperado.lower() not in output.lower():
            fallos.append(f"no contiene {esperado!r}")

    for prohibido in expect.not_contains:
        if prohibido.lower() in output.lower():
            fallos.append(f"contiene {prohibido!r} y no debía")

    if expect.matches and not re.search(expect.matches, output, re.IGNORECASE | re.DOTALL):
        fallos.append(f"no casa con /{expect.matches}/")

    if expect.max_chars and len(output) > expect.max_chars:
        fallos.append(f"{len(output)} caracteres, máximo {expect.max_chars}")

    if expect.min_chars and len(output) < expect.min_chars:
        fallos.append(f"{len(output)} caracteres, mínimo {expect.min_chars}")

    if expect.json_valid:
        try:
            json.loads(output)
        except (ValueError, TypeError):
            fallos.append("no es JSON válido")

    return fallos


async def run_suite(
    suite: EvalSuite,
    criterios: dict[str, Criterion],
    *,
    run: Callable[[str], Awaitable[str]],
    judge: Callable[[str], Awaitable[str]] | None = None,
    only_tag: str | None = None,
) -> SuiteResult:
    """Ejecutar cada caso y puntuar.

    ``run`` y ``judge`` se pasan desde fuera para que este módulo no sepa de
    ningún framework: son dos corrutinas que reciben texto y devuelven texto.
    """
    resultado = SuiteResult(suite=suite, judged=judge is not None)

    for caso in suite.spec.cases:
        if only_tag and only_tag not in caso.tags:
            continue

        actual = CaseResult(case=caso)
        try:
            actual.output = await run(caso.input)
        except Exception as exc:  # noqa: BLE001 - un fallo de ejecución es un fallo del caso
            actual.error = f"{type(exc).__name__}: {exc}"
            resultado.cases.append(actual)
            continue

        actual.failures = evaluate_assertions(actual.output, caso.expect)

        if caso.judge and judge is not None:
            for nombre in caso.judge:
                veredicto = await _ask_judge(judge, criterios[nombre], caso, actual.output)
                actual.judged[nombre] = veredicto
                if not veredicto:
                    actual.failures.append(f"el juez rechaza '{nombre}'")

        resultado.cases.append(actual)

    return resultado


async def _ask_judge(
    judge: Callable[[str], Awaitable[str]], criterio: Criterion, caso: EvalCase, output: str
) -> bool:
    """Preguntar al juez por un criterio. Ante la duda, suspende.

    Si el juez devuelve algo que no se entiende, el caso falla. Lo contrario
    —dar por bueno lo que no se pudo leer— convierte la suite en decorado.
    """
    peticion = json.dumps(
        {"criterio": criterio.question, "entrada": caso.input, "respuesta": output},
        ensure_ascii=False,
    )
    crudo = await judge(peticion)

    encontrado = re.search(r'"pass"\s*:\s*(true|false)', crudo, re.IGNORECASE)
    if encontrado:
        return encontrado.group(1).lower() == "true"

    texto = crudo.strip().lower()
    if texto.startswith(("sí", "si", "yes", "pass", "true")):
        return True
    return False


