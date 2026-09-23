"""Escalón 3 en LangGraph, a mano.

    python examples/03-multi-agente/en_langgraph.py
"""

from __future__ import annotations

from langchain_core.tools import StructuredTool
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.prebuilt import create_react_agent


def modelo():
    return ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0.1)


def especialista(nombre: str, instruccion: str):
    return create_react_agent(model=modelo(), tools=[], prompt=instruccion, name=nombre)


def como_herramienta(grafo, nombre: str, descripcion: str):
    """Un grafo compilado se convierte en herramienta invocándolo.

    No hay nada especial en ello: `invoke` toma mensajes y devuelve mensajes, así
    que envolverlo en una función es todo lo que hace falta. Ese es el beneficio
    de que en LangGraph un agente ya sea un grafo.
    """

    def llamar(peticion: str) -> str:
        estado = grafo.invoke({"messages": [{"role": "user", "content": peticion}]})
        return estado["messages"][-1].content

    llamar.__doc__ = descripcion
    return StructuredTool.from_function(func=llamar, name=nombre, description=descripcion)


def construir():
    desarrollador = especialista(
        "python_developer",
        "You are a senior Python developer. Given a requirement, write one clean, "
        "PEP8-compliant function with type hints and a docstring.",
    )
    revisor = especialista(
        "code_reviewer",
        "You are a code reviewer. Report correctness bugs and edge cases first, "
        "then real performance or security concerns.",
    )

    return create_react_agent(
        model=modelo(),
        tools=[
            como_herramienta(
                desarrollador,
                "python_developer",
                "Writes a Python function that satisfies a requirement.",
            ),
            como_herramienta(
                revisor,
                "code_reviewer",
                "Reviews Python code and reports bugs, risks and improvements.",
            ),
        ],
        prompt=(
            "You are a software development manager. You never write or review code "
            "yourself. Delegate the implementation to python_developer, then send the "
            "result to code_reviewer, and summarise both."
        ),
        name="software_manager",
    )


def main() -> None:
    agente = construir()
    estado = agente.invoke(
        {"messages": [{"role": "user", "content": "Necesito una función que valide un IBAN"}]}
    )
    print(estado["messages"][-1].content)


if __name__ == "__main__":
    main()
