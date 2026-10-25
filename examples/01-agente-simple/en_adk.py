"""Escalón 1 en Google ADK, a mano.

El equivalente de `catalog/agents/technology/tech-explainer/agent.yaml`, escrito sin plataforma.

    python examples/01-agente-simple/en_adk.py
"""

from __future__ import annotations

import asyncio

from google.adk.agents import LlmAgent
from google.adk.apps import App
from google.adk.runners import InMemoryRunner
from google.genai import types

INSTRUCCION = """Explicas conceptos de tecnología a una persona de negocio sin formación técnica.

Responde en tres frases como mucho: qué es, para qué sirve y un ejemplo
cotidiano. Sin jerga; si un término técnico es inevitable, defínelo en la misma
frase.

No tienes herramientas ni acceso a internet. Si te preguntan por datos actuales
(precios, versiones, cifras de hoy), di claramente que no puedes consultarlos en
lugar de dar una cifra."""


def construir() -> App:
    """En ADK el agente y la aplicación son cosas distintas.

    El `LlmAgent` es la definición; la `App` es lo que se ejecuta y lo que lleva
    los plugins. Esa separación es la que la plataforma aprovecha para meter
    guardrails y permisos sin tocar el agente.
    """
    agente = LlmAgent(
        name="tech_explainer",
        model="gemini-2.5-flash",
        description="Explica un concepto técnico en lenguaje claro, en tres frases.",
        instruction=INSTRUCCION,
        generate_content_config=types.GenerateContentConfig(temperature=0.7),
    )
    return App(name="tech_explainer", root_agent=agente)


async def main() -> None:
    app = construir()
    runner = InMemoryRunner(app=app)

    # ADK conversa sobre una sesión: hay que crearla antes de hablar.
    await runner.session_service.create_session(
        app_name=runner.app_name, user_id="demo", session_id="demo-1"
    )

    mensaje = types.Content(role="user", parts=[types.Part.from_text(text="¿Qué es una API REST?")])
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
