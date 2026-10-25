"""Escalón 1 en LangGraph, a mano.

    python examples/01-agente-simple/en_langgraph.py
"""

from __future__ import annotations

from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.prebuilt import create_react_agent

INSTRUCCION = """Explicas conceptos de tecnología a una persona de negocio sin formación técnica.

Responde en tres frases como mucho: qué es, para qué sirve y un ejemplo
cotidiano. Sin jerga; si un término técnico es inevitable, defínelo en la misma
frase.

No tienes herramientas ni acceso a internet. Si te preguntan por datos actuales
(precios, versiones, cifras de hoy), di claramente que no puedes consultarlos en
lugar de dar una cifra."""


def construir():
    """`create_react_agent` sin tools sigue siendo un grafo.

    Merece la pena verlo así desde el principio: en LangGraph no hay un tipo
    "agente" aparte. Un agente es un grafo compilado, y por eso más adelante se
    puede componer con otros grafos sin ninguna costura.
    """
    return create_react_agent(
        model=ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0.7),
        tools=[],
        prompt=INSTRUCCION,
        name="tech_explainer",
    )


def main() -> None:
    agente = construir()
    estado = agente.invoke({"messages": [{"role": "user", "content": "¿Qué es una API REST?"}]})
    print(estado["messages"][-1].content)

    # Todo grafo compilado sabe dibujarse. Con un solo nodo no dice mucho,
    # pero en el escalón 4 es la forma más rápida de ver qué has montado.
    print("\n" + agente.get_graph().draw_ascii())


if __name__ == "__main__":
    main()
