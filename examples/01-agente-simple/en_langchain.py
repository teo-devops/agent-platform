"""Escalón 1 en LangChain, a mano.

    python examples/01-agente-simple/en_langchain.py
"""

from __future__ import annotations

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_google_genai import ChatGoogleGenerativeAI

INSTRUCCION = """You are a warm, extremely polite assistant.

Greet the user by acknowledging what they asked, then answer their question
with enthusiasm and in at most three sentences. If a question needs a tool or
data you do not have, say so plainly instead of guessing."""


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
    modelo = ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=1.0)
    return prompt | modelo | StrOutputParser()


def main() -> None:
    print(construir().invoke({"pregunta": "¿Qué tal?"}))


if __name__ == "__main__":
    main()
