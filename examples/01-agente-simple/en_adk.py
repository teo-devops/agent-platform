"""Escalón 1 en Google ADK, a mano.

El equivalente de `agents/greeting/agent.yaml`, escrito sin plataforma.

    python examples/01-agente-simple/en_adk.py
"""

from __future__ import annotations

import asyncio

from google.adk.agents import LlmAgent
from google.adk.apps import App
from google.adk.runners import InMemoryRunner
from google.genai import types

INSTRUCCION = """You are a warm, extremely polite assistant.

Greet the user by acknowledging what they asked, then answer their question
with enthusiasm and in at most three sentences. If a question needs a tool or
data you do not have, say so plainly instead of guessing."""


def construir() -> App:
    """En ADK el agente y la aplicación son cosas distintas.

    El `LlmAgent` es la definición; la `App` es lo que se ejecuta y lo que lleva
    los plugins. Esa separación es la que la plataforma aprovecha para meter
    guardrails y permisos sin tocar el agente.
    """
    agente = LlmAgent(
        name="greeting",
        model="gemini-2.5-flash",
        description="Greets the user and answers short questions with enthusiasm.",
        instruction=INSTRUCCION,
        generate_content_config=types.GenerateContentConfig(temperature=1.0),
    )
    return App(name="greeting", root_agent=agente)


async def main() -> None:
    app = construir()
    runner = InMemoryRunner(app=app)

    # ADK conversa sobre una sesión: hay que crearla antes de hablar.
    await runner.session_service.create_session(
        app_name=runner.app_name, user_id="demo", session_id="demo-1"
    )

    mensaje = types.Content(role="user", parts=[types.Part.from_text(text="¿Qué tal?")])
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
