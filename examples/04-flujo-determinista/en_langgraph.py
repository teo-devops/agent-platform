"""Escalón 4 en LangGraph, a mano.

    python examples/04-flujo-determinista/en_langgraph.py
"""

from __future__ import annotations

from typing import TypedDict

from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import create_react_agent


class Estado(TypedDict, total=False):
    """Lo que viaja entre pasos.

    En LangGraph el estado es **explícito**: lo declaras y ves exactamente qué
    escribe cada nodo. Es la diferencia grande con el `output_key` de ADK, que
    deja el valor en el estado de sesión sin que el grafo lo declare.
    """

    tema: str
    notas: str
    articulo: str


def modelo():
    return ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0.1)


def _responder(agente, peticion: str) -> str:
    estado = agente.invoke({"messages": [{"role": "user", "content": peticion}]})
    return estado["messages"][-1].content


def construir():
    """Nodos y aristas: es el escalón donde el manifiesto y el framework coinciden.

    Compara este grafo con `catalog/workflows/tech-article.yaml`. Son la misma cosa
    escrita en dos sitios — por eso el runtime de LangGraph de esta plataforma
    es una traducción tan directa.
    """
    investigador = create_react_agent(
        model=modelo(),
        tools=[],
        prompt=(
            "Eres analista de tecnología. Prepara notas estructuradas: qué es, "
            "estado actual, alternativas, riesgos y preguntas abiertas. Marca "
            "como *a verificar* lo que no puedas asegurar."
        ),
        name="research",
    )
    redactor = create_react_agent(
        model=modelo(),
        tools=[],
        prompt=(
            "Eres redactor del blog de ingeniería. Convierte las notas en un "
            "artículo en Markdown. Conserva cada afirmación de las notas."
        ),
        name="write",
    )

    grafo = StateGraph(Estado)
    grafo.add_node("research", lambda s: {"notas": _responder(investigador, s["tema"])})
    grafo.add_node("write", lambda s: {"articulo": _responder(redactor, s["notas"])})

    grafo.add_edge(START, "research")
    grafo.add_edge("research", "write")
    grafo.add_edge("write", END)

    return grafo.compile(name="tech_article")


def main() -> None:
    flujo = construir()
    print(flujo.get_graph().draw_ascii())
    print(flujo.invoke({"tema": "WebAssembly en el servidor"})["articulo"])


if __name__ == "__main__":
    main()
