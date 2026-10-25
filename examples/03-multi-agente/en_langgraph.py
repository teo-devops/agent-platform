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
        "Eres desarrollador Python senior. Dado un requisito, escribe una única "
        "función limpia, conforme a PEP 8, con type hints y docstring.",
    )
    revisor = especialista(
        "code_reviewer",
        "Eres revisor de código. Informa primero de bugs y casos límite, "
        "después de problemas reales de rendimiento o seguridad.",
    )

    return create_react_agent(
        model=modelo(),
        tools=[
            como_herramienta(
                desarrollador,
                "python_developer",
                "Escribe una función Python que cumple un requisito.",
            ),
            como_herramienta(
                revisor,
                "code_reviewer",
                "Revisa código Python y devuelve bugs, riesgos y mejoras.",
            ),
        ],
        prompt=(
            "Eres jefe de desarrollo. Nunca escribes ni revisas código tú. Delega "
            "la implementación en python_developer, pasa el resultado a "
            "code_reviewer y resume ambos."
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
