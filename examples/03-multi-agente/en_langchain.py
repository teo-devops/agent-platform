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
        "Eres desarrollador Python senior. Dado un requisito, escribe una única "
        "función limpia, conforme a PEP 8, con type hints y docstring.",
    )
    revisor = especialista(
        "code_reviewer",
        "Eres revisor de código. Informa primero de bugs y casos límite, "
        "después de problemas reales de rendimiento o seguridad.",
    )

    return create_agent(
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
        system_prompt=(
            "Eres jefe de desarrollo. Nunca escribes ni revisas código tú. Delega "
            "la implementación en python_developer, pasa el resultado a "
            "code_reviewer y resume ambos."
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
