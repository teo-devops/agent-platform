"""Escalón 2 en LangGraph, a mano.

    python examples/02-tools/en_langgraph.py
"""

from __future__ import annotations

from langchain_core.tools import StructuredTool
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.prebuilt import create_react_agent


def calculate_bmi(weight_kg: float, height_m: float) -> dict:
    """Calculates the Body Mass Index (BMI) from weight and height.

    Args:
        weight_kg: Body weight in kilograms.
        height_m: Height in metres.

    Returns:
        A dict with the bmi value rounded to one decimal.
    """
    if height_m <= 0:
        return {"error": "height must be greater than zero"}
    return {"bmi": round(weight_kg / (height_m**2), 1)}


def get_advice(bmi: float) -> dict:
    """Explains what a BMI value means.

    Args:
        bmi: The Body Mass Index value.

    Returns:
        A dict with the category the value falls into.
    """
    if bmi < 18.5:
        return {"category": "underweight"}
    if bmi < 25:
        return {"category": "healthy range"}
    if bmi < 30:
        return {"category": "overweight"}
    return {"category": "obese"}


def construir():
    """El grafo ReAct ya trae montado el bucle modelo -> tool -> modelo.

    Es exactamente el mismo grafo del escalón 1, pero con una arista condicional:
    si el modelo pidió una herramienta, se va al nodo de tools y se vuelve. Eso
    es todo lo que un "agente" es.
    """
    herramientas = [
        StructuredTool.from_function(func=calculate_bmi),
        StructuredTool.from_function(func=get_advice),
    ]
    return create_react_agent(
        model=ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0.1),
        tools=herramientas,
        prompt=(
            "You are a health assistant. Use calculate_bmi to compute the index "
            "and get_advice to explain it. Never guess the numbers yourself."
        ),
        name="health_advisor",
    )


def main() -> None:
    agente = construir()
    estado = agente.invoke(
        {"messages": [{"role": "user", "content": "Peso 80 kg y mido 1.82 m, ¿cómo estoy?"}]}
    )
    # El historial completo deja ver las llamadas a herramienta, que es lo que
    # de verdad hay que mirar cuando un agente con tools se porta raro.
    for mensaje in estado["messages"]:
        mensaje.pretty_print()


if __name__ == "__main__":
    main()
