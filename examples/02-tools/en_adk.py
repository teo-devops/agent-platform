"""Escalón 2 en Google ADK, a mano.

    python examples/02-tools/en_adk.py
"""

from __future__ import annotations

import asyncio

from google.adk.agents import LlmAgent
from google.adk.apps import App
from google.adk.runners import InMemoryRunner
from google.adk.tools import FunctionTool
from google.genai import types


def calculate_bmi(weight_kg: float, height_m: float) -> dict:
    """Calculates the Body Mass Index (BMI) from weight and height.

    Args:
        weight_kg: Body weight in kilograms.
        height_m: Height in metres.

    Returns:
        A dict with the bmi value rounded to one decimal.
    """
    # Este docstring no es decoración: es lo que lee el modelo para decidir si
    # llama a la función y qué le pasa. ADK lo convierte en el esquema JSON.
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
        categoria = "underweight"
    elif bmi < 25:
        categoria = "healthy range"
    elif bmi < 30:
        categoria = "overweight"
    else:
        categoria = "obese"
    return {"category": categoria}


def construir() -> App:
    agente = LlmAgent(
        name="health_advisor",
        model="gemini-2.5-flash",
        instruction=(
            "You are a health assistant. Use calculate_bmi to compute the index "
            "and get_advice to explain it. Never guess the numbers yourself."
        ),
        tools=[FunctionTool(func=calculate_bmi), FunctionTool(func=get_advice)],
    )
    return App(name="health_advisor", root_agent=agente)


async def main() -> None:
    runner = InMemoryRunner(app=construir())
    await runner.session_service.create_session(
        app_name=runner.app_name, user_id="demo", session_id="demo-1"
    )
    mensaje = types.Content(
        role="user",
        parts=[types.Part.from_text(text="Peso 80 kg y mido 1.82 m, ¿cómo estoy?")],
    )
    async for evento in runner.run_async(
        user_id="demo", session_id="demo-1", new_message=mensaje
    ):
        if evento.content and evento.content.parts:
            for parte in evento.content.parts:
                if getattr(parte, "text", None):
                    print(parte.text, end="", flush=True)
    print()


if __name__ == "__main__":
    asyncio.run(main())
