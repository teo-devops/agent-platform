"""Evaluación: medir si un cambio mejora o empeora, en vez de suponerlo.

Sin esto, cambiar un prompt es una edición a ciegas: se lee la nueva respuesta,
parece mejor, y nadie sabe qué se rompió en los otros veinte casos. Con esto,
cambiar un prompt produce un número comparable con el de antes.

Dos niveles, y el orden importa:

1. **Aserciones deterministas** — sin modelo, sin red, sin fluctuación. Todo lo
   que se pueda comprobar aquí no debe delegarse en un juez.
2. **Juez LLM** — sólo para lo que de verdad necesita criterio: tono, estructura,
   si algo se ha inventado.

El juez es **un agente más del catálogo** (`eval-judge`), construido con la misma
fábrica que todo lo demás. Así no hace falta una superficie nueva de protocolo, y
el juez se versiona, se revisa y se evalúa como cualquier otro agente.
"""

from .engine import CaseResult, SuiteResult, evaluate_assertions, load_suite, run_suite
from .schemas import Assertion, Criterion, EvalCase, EvalSuite, EvalSuiteBody

__all__ = [
    "Assertion",
    "CaseResult",
    "Criterion",
    "EvalCase",
    "EvalSuite",
    "EvalSuiteBody",
    "SuiteResult",
    "evaluate_assertions",
    "load_suite",
    "run_suite",
]
