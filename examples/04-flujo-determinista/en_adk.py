"""Escalón 4 en Google ADK, a mano.

    python examples/04-flujo-determinista/en_adk.py
"""

from __future__ import annotations

import asyncio

from google.adk import Workflow
from google.adk.agents import LlmAgent
from google.adk.apps import App
from google.adk.runners import InMemoryRunner
from google.adk.workflow import START
from google.genai import types


def construir() -> App:
    """Aristas explícitas sobre el grafo de bajo nivel de ADK.

    ADK trae `SequentialAgent` y `ParallelAgent` ya hechos, pero aquí se usa
    `Workflow` con aristas porque es lo que generaliza: en línea, en abanico y
    cualquier topología son el mismo mecanismo con distintas aristas. Es también
    lo que hace la plataforma, y lo que permite que la misma declaración valga
    para LangGraph.
    """
    investigador = LlmAgent(
        name="research",
        model="gemini-2.5-flash",
        instruction=(
            "You are an academic researcher. Produce structured research notes: "
            "key facts, background, state of the art and open questions. Mark "
            "anything uncertain as uncertain."
        ),
        output_key="research_notes",
    )
    redactor = LlmAgent(
        name="write",
        model="gemini-2.5-flash",
        instruction=(
            "You are a science communicator. Turn the research notes into a "
            "Markdown article. Keep every factual claim intact."
        ),
        output_key="article",
    )

    flujo = Workflow(
        name="research_and_write",
        description="Deterministic research pipeline.",
        edges=[(START, investigador), (investigador, redactor)],
    )
    return App(name="research_and_write", root_agent=flujo)


async def main() -> None:
    runner = InMemoryRunner(app=construir())
    await runner.session_service.create_session(
        app_name=runner.app_name, user_id="demo", session_id="demo-1"
    )
    mensaje = types.Content(
        role="user", parts=[types.Part.from_text(text="arquitectura hexagonal")]
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
