"""El contrato de una suite de evaluación.

Una suite vive en ``evals/<nombre>/`` y son dos ficheros, por la misma razón que
el resto del repositorio separa manifiesto y perfiles: los **casos** cambian cada
vez que aparece un fallo nuevo, y los **criterios** son estables y se comparten
entre casos.

    evals/<nombre>/dataset.yaml   qué se le pide y qué debe cumplir
    evals/<nombre>/judges.yaml    los criterios que evalúa un modelo
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from ..schemas.common import Spec


class Assertion(Spec):
    """Comprobaciones deterministas sobre la respuesta.

    Se ejecutan sin llamar a ningún modelo, así que son gratis, instantáneas y
    no fluctúan. Todo lo que se pueda comprobar aquí no debería delegarse en un
    juez: un `contains` no tiene falsos negativos y un juez sí.
    """

    contains: list[str] = Field(default_factory=list, description="Todas estas cadenas deben aparecer.")
    not_contains: list[str] = Field(default_factory=list, description="Ninguna de estas debe aparecer.")
    matches: str | None = Field(default=None, description="Expresión regular que debe encontrar algo.")
    max_chars: int | None = Field(default=None, ge=1, description="Longitud máxima de la respuesta.")
    min_chars: int | None = Field(default=None, ge=1, description="Longitud mínima de la respuesta.")
    json_valid: bool = Field(default=False, description="La respuesta debe ser JSON válido.")

    @property
    def is_empty(self) -> bool:
        return not (
            self.contains
            or self.not_contains
            or self.matches
            or self.max_chars
            or self.min_chars
            or self.json_valid
        )


class EvalCase(Spec):
    """Un caso: una entrada y lo que se espera de la salida."""

    id: str = Field(description="Identificador del caso. Aparece en el informe.")
    input: str = Field(description="Lo que se le envía al agente o flujo.")
    description: str = Field(default="", description="Por qué existe este caso.")
    expect: Assertion = Field(default_factory=Assertion, description="Comprobaciones deterministas.")
    judge: list[str] = Field(
        default_factory=list,
        description="Criterios de judges.yaml que debe cumplir. Requieren llamar a un modelo.",
    )
    tags: list[str] = Field(default_factory=list, description="Para filtrar con --tag.")


class EvalSuiteBody(Spec):
    target: str = Field(description="Agente o flujo que se evalúa.")
    metric: str = Field(default="pass_at_1", description="Nombre de la métrica que se publica.")
    threshold: float = Field(default=0.8, ge=0, le=1, description="Proporción mínima de casos que deben pasar.")
    goal: Literal["maximize", "minimize"] = Field(default="maximize", description="De qué lado del umbral hay que estar.")
    cases: list[EvalCase] = Field(default_factory=list, description="Los casos, en orden.")


class EvalSuite(Spec):
    apiVersion: str = "agents.platform/v1"
    kind: Literal["EvalSuite"] = "EvalSuite"
    metadata: dict = Field(default_factory=dict)
    spec: EvalSuiteBody

    @property
    def name(self) -> str:
        return self.metadata.get("name", self.spec.target)


class Criterion(Spec):
    """Un criterio que evalúa un modelo, no una regla.

    Reservado para lo que no se puede comprobar con una aserción: tono,
    estructura, si una respuesta se ha inventado algo. Si se puede escribir como
    `contains`, escríbelo como `contains`.
    """

    question: str = Field(description="La pregunta que se le hace al juez, en sí/no.")
    weight: float = Field(default=1.0, gt=0, description="Cuánto pesa dentro del caso.")
