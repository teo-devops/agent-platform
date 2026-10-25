"""Escalón 1 en LangChain, a mano.

    python examples/01-agente-simple/en_langchain.py
"""

from __future__ import annotations

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_google_genai import ChatGoogleGenerativeAI

INSTRUCCION = """Explicas conceptos de tecnología a una persona de negocio sin formación técnica.

Responde en tres frases como mucho: qué es, para qué sirve y un ejemplo
cotidiano. Sin jerga; si un término técnico es inevitable, defínelo en la misma
frase.

No tienes herramientas ni acceso a internet. Si te preguntan por datos actuales
(precios, versiones, cifras de hoy), di claramente que no puedes consultarlos en
lugar de dar una cifra."""


def construir():
    """Aquí no hace falta un agente: una cadena basta.

    Un agente es un bucle que decide si llamar a una herramienta y cuándo parar.
    Sin herramientas no hay nada que decidir, así que ese bucle sólo añadiría
    latencia. LCEL encadena con `|`: plantilla, modelo, parser.

    Saber cuándo NO necesitas un agente es la mitad de esto.
    """
    prompt = ChatPromptTemplate.from_messages(
        [("system", INSTRUCCION), ("human", "{pregunta}")]
    )
    modelo = ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0.7)
    return prompt | modelo | StrOutputParser()


def main() -> None:
    print(construir().invoke({"pregunta": "¿Qué es una API REST?"}))


if __name__ == "__main__":
    main()
