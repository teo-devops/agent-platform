"""Escalón 3 en Google ADK, a mano.

    python examples/03-multi-agente/en_adk.py
"""

from __future__ import annotations

import asyncio

from google.adk.agents import LlmAgent
from google.adk.apps import App
from google.adk.runners import InMemoryRunner
from google.adk.tools.agent_tool import AgentTool
from google.genai import types


def especialistas() -> tuple[LlmAgent, LlmAgent]:
    desarrollador = LlmAgent(
        name="python_developer",
        model="gemini-2.5-flash",
        instruction=(
            "Eres desarrollador Python senior. Dado un requisito, escribe una única "
            "función limpia, conforme a PEP 8, con type hints y docstring."
        ),
    )
    revisor = LlmAgent(
        name="code_reviewer",
        model="gemini-2.5-flash",
        instruction=(
            "Eres revisor de código. Informa primero de bugs y casos límite, "
            "después de problemas reales de rendimiento o seguridad."
        ),
    )
    return desarrollador, revisor


def construir() -> App:
    """Delegación por herramienta: el coordinador no suelta el control.

    `AgentTool` convierte un agente en algo que el coordinador llama igual que
    llamaría a una función de `catalog/tools/`. La alternativa —pasar los hijos en
    `sub_agents=[...]`— haría que ADK pudiera transferirles el turno, y entonces
    quien responde al usuario deja de ser quien tú crees.
    """
    desarrollador, revisor = especialistas()

    coordinador = LlmAgent(
        name="software_manager",
        model="gemini-2.5-flash",
        instruction=(
            "Eres jefe de desarrollo. Nunca escribes ni revisas código tú. Delega "
            "la implementación en python_developer, pasa el resultado a "
            "code_reviewer y resume ambos."
        ),
        tools=[AgentTool(agent=desarrollador), AgentTool(agent=revisor)],
        # sub_agents=[desarrollador, revisor],  # <- esto sería 'transfer'
    )
    return App(name="software_manager", root_agent=coordinador)


async def main() -> None:
    runner = InMemoryRunner(app=construir())
    await runner.session_service.create_session(
        app_name=runner.app_name, user_id="demo", session_id="demo-1"
    )
    mensaje = types.Content(
        role="user",
        parts=[types.Part.from_text(text="Necesito una función que valide un IBAN")],
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
