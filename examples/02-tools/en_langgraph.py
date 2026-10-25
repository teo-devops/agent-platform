"""Escalón 2 en LangGraph, a mano.

    python examples/02-tools/en_langgraph.py
"""

from __future__ import annotations

import re

from langchain_core.tools import StructuredTool
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.prebuilt import create_react_agent


def next_version(current: str, log: str) -> dict:
    """Computes the next semantic version from the current one and a commit log.

    A breaking change ("type!:" or "BREAKING CHANGE") bumps the major version, a
    feature ("feat:") the minor one, and anything else the patch.

    Args:
        current: The version released last, e.g. "1.4.2".
        log: Commit subjects since that release, one per line (Conventional Commits).

    Returns:
        A dict with the 'next' version and the 'bump' applied, or an 'error'.
    """
    # Este docstring no es decoración: es lo que lee el modelo para decidir si
    # llama a la función y qué le pasa. El framework lo convierte en el esquema JSON.
    try:
        major, minor, patch = (int(n) for n in current.strip().lstrip("v").split("."))
    except ValueError:
        return {"error": f"'{current}' is not a semantic version like 1.4.2"}
    lines = [line.strip() for line in log.splitlines() if line.strip()]
    if any(re.match(r"^[a-z]+(\(.+\))?!:", line) or line.startswith("BREAKING CHANGE") for line in lines):
        return {"next": f"{major + 1}.0.0", "bump": "major"}
    if any(re.match(r"^feat(\(.+\))?:", line) for line in lines):
        return {"next": f"{major}.{minor + 1}.0", "bump": "minor"}
    return {"next": f"{major}.{minor}.{patch + 1}", "bump": "patch"}


def parse_commits(log: str) -> dict:
    """Groups a commit log, one Conventional Commits subject per line, by type.

    Args:
        log: Commit subjects separated by newlines, e.g. "fix(api): handle timeouts".

    Returns:
        A dict with the subjects grouped under 'features', 'fixes' and 'other'.
    """
    groups: dict[str, list[str]] = {"features": [], "fixes": [], "other": []}
    for line in (line.strip() for line in log.splitlines()):
        match = re.match(r"^([a-z]+)(\(.+\))?!?:\s*(.+)$", line)
        if match:
            key = {"feat": "features", "fix": "fixes"}.get(match[1], "other")
            groups[key].append(match[3])
    return groups

def construir():
    """El grafo ReAct ya trae montado el bucle modelo -> tool -> modelo.

    Es exactamente el mismo grafo del escalón 1, pero con una arista condicional:
    si el modelo pidió una herramienta, se va al nodo de tools y se vuelve. Eso
    es todo lo que un "agente" es.
    """
    herramientas = [
        StructuredTool.from_function(func=next_version),
        StructuredTool.from_function(func=parse_commits),
    ]
    return create_react_agent(
        model=ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0.1),
        tools=herramientas,
        prompt=(
            "Eres el responsable de releases. Llama a next_version y a parse_commits "
            "con la versión y los commits que te den; no calcules la versión tú. "
            "Responde con la versión nueva, por qué ese salto y las notas agrupadas."
        ),
        name="release_manager",
    )


def main() -> None:
    agente = construir()
    estado = agente.invoke(
        {"messages": [{"role": "user", "content": "Versión actual: 1.4.2.\nfeat(api): paginación en /orders\nfix: cierre de conexiones al reiniciar"}]}
    )
    # El historial completo deja ver las llamadas a herramienta, que es lo que
    # de verdad hay que mirar cuando un agente con tools se porta raro.
    for mensaje in estado["messages"]:
        mensaje.pretty_print()


if __name__ == "__main__":
    main()
