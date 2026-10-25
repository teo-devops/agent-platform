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
        "Eres analista de tecnología. Prepara notas estructuradas: qué es, "
        "estado actual, alternativas, riesgos y preguntas abiertas. Marca "
        "como *a verificar* lo que no puedas asegurar.",
        "tema",
    )
    redactar = paso(
        "Eres redactor del blog de ingeniería. Convierte las notas en un "
        "artículo en Markdown. Conserva cada afirmación de las notas.",
        "notas",
    )
    return investigar | (lambda notas: {"notas": notas}) | redactar


def construir_en_abanico():
    """El mismo `tech-briefing` del repositorio: una tecnología, dos audiencias a la vez."""
    return RunnableParallel(
        technical=paso("Eres analista de tecnología. Dame los hechos clave y los riesgos.", "tema"),
        executive=paso("Explícalo a alguien de negocio en tres frases, sin jerga.", "tema"),
    )


def main() -> None:
    print(construir().invoke({"tema": "WebAssembly en el servidor"}))


if __name__ == "__main__":
    main()
