"""Escalón 4 en LangChain, a mano.

    python examples/04-flujo-determinista/en_langchain.py
"""

from __future__ import annotations

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableParallel
from langchain_google_genai import ChatGoogleGenerativeAI


def modelo():
    return ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0.1)


def paso(instruccion: str, variable: str):
    prompt = ChatPromptTemplate.from_messages(
        [("system", instruccion), ("human", "{" + variable + "}")]
    )
    return prompt | modelo() | StrOutputParser()


def construir():
    """LCEL encadena con `|`, y eso cubre la línea y el abanico.

    Lo que NO cubre —y conviene saberlo antes de empezar, no después— es una
    topología arbitraria o un bucle con condición de parada. LCEL son cadenas: no
    hay aristas que puedas dibujar a tu gusto ni vuelta atrás. En cuanto tu flujo
    necesite eso, el sitio es LangGraph o ADK.

    `RunnableParallel`, abajo, es el abanico: varias ramas sobre la misma
    entrada, ejecutadas a la vez.
    """
    investigar = paso(
        "You are an academic researcher. Produce structured research notes: "
        "key facts, background, state of the art and open questions.",
        "tema",
    )
    redactar = paso(
        "You are a science communicator. Turn the research notes into a "
        "Markdown article. Keep every factual claim intact.",
        "notas",
    )
    return investigar | (lambda notas: {"notas": notas}) | redactar


def construir_en_abanico():
    """El mismo `parallel-briefing` del repositorio: dos ramas, una entrada."""
    return RunnableParallel(
        research=paso("You are an academic researcher. Give me the key facts.", "tema"),
        explain=paso("You are a warm assistant. Explain it in three sentences.", "tema"),
    )


def main() -> None:
    print(construir().invoke({"tema": "arquitectura hexagonal"}))


if __name__ == "__main__":
    main()
