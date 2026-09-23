"""Escalón 3 en LangChain, a mano.

    python examples/03-multi-agente/en_langchain.py
"""

from __future__ import annotations

from langchain.agents import create_agent
from langchain_core.tools import StructuredTool
from langchain_google_genai import ChatGoogleGenerativeAI


def modelo():
    return ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0.1)


def especialista(nombre: str, instruccion: str):
    return create_agent(model=modelo(), tools=[], system_prompt=instruccion, name=nombre)


def como_herramienta(agente, nombre: str, descripcion: str):
    def llamar(peticion: str) -> str:
        estado = agente.invoke({"messages": [{"role": "user", "content": peticion}]})
        return estado["messages"][-1].content

    return StructuredTool.from_function(func=llamar, name=nombre, description=descripcion)


def construir():
    """En LangChain sólo existe la delegación por herramienta.

    No hay equivalente a ceder el turno: un agente llama a otro y recibe una
    respuesta, punto. Si tu diseño depende de que el control se mueva de verdad
    de un agente a otro, ese diseño no cabe aquí — y conviene descubrirlo ahora y
    no a mitad de la implementación.
    """
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

    return create_agent(
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
        system_prompt=(
            "You are a software development manager. You never write or review code "
            "yourself. Delegate the implementation to python_developer, then send the "
            "result to code_reviewer, and summarise both."
        ),
        name="software_manager",
    )


def main() -> None:
    estado = construir().invoke(
        {"messages": [{"role": "user", "content": "Necesito una función que valide un IBAN"}]}
    )
    print(estado["messages"][-1].content)


if __name__ == "__main__":
    main()
