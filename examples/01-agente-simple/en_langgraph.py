"""Escalón 1 en LangGraph, a mano.

    python examples/01-agente-simple/en_langgraph.py
"""

from __future__ import annotations

from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.prebuilt import create_react_agent

INSTRUCCION = """You are a warm, extremely polite assistant.

Greet the user by acknowledging what they asked, then answer their question
with enthusiasm and in at most three sentences. If a question needs a tool or
data you do not have, say so plainly instead of guessing."""


def construir():
    """`create_react_agent` sin tools sigue siendo un grafo.

    Merece la pena verlo así desde el principio: en LangGraph no hay un tipo
    "agente" aparte. Un agente es un grafo compilado, y por eso más adelante se
    puede componer con otros grafos sin ninguna costura.
    """
    return create_react_agent(
        model=ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=1.0),
        tools=[],
        prompt=INSTRUCCION,
        name="greeting",
    )


def main() -> None:
    agente = construir()
    estado = agente.invoke({"messages": [{"role": "user", "content": "¿Qué tal?"}]})
    print(estado["messages"][-1].content)

    # Todo grafo compilado sabe dibujarse. Con un solo nodo no dice mucho,
    # pero en el escalón 4 es la forma más rápida de ver qué has montado.
    print("\n" + agente.get_graph().draw_ascii())


if __name__ == "__main__":
    main()
