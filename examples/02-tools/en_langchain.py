"""Escalón 2 en LangChain, a mano.

    python examples/02-tools/en_langchain.py
"""

from __future__ import annotations

from langchain.agents import create_agent
from langchain_core.tools import StructuredTool
from langchain_google_genai import ChatGoogleGenerativeAI


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
    """`create_agent` es el equivalente en LangChain 1.x.

    Conviene saber qué devuelve: un `CompiledStateGraph`, es decir, un grafo de
    LangGraph. LangChain 1.x construye sus agentes encima de LangGraph, así que
    este ejemplo y el de al lado son más parecidos por dentro de lo que parecen
    por fuera. Consecuencia práctica: `langgraph dev` sirve a los dos.
    """
    return create_agent(
        model=ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0.1),
        tools=[
            StructuredTool.from_function(func=calculate_bmi),
            StructuredTool.from_function(func=get_advice),
        ],
        system_prompt=(
            "You are a health assistant. Use calculate_bmi to compute the index "
            "and get_advice to explain it. Never guess the numbers yourself."
        ),
        name="health_advisor",
    )


def main() -> None:
    agente = construir()
    print("tipo real:", type(agente).__name__)
    estado = agente.invoke(
        {"messages": [{"role": "user", "content": "Peso 80 kg y mido 1.82 m, ¿cómo estoy?"}]}
    )
    print(estado["messages"][-1].content)


if __name__ == "__main__":
    main()
