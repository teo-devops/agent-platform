"""Escalón 2 en Google ADK, a mano.

    python examples/02-tools/en_adk.py
"""

from __future__ import annotations

import re

import asyncio

from google.adk.agents import LlmAgent
from google.adk.apps import App
from google.adk.runners import InMemoryRunner
from google.adk.tools import FunctionTool
from google.genai import types


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

def construir() -> App:
    agente = LlmAgent(
        name="release_manager",
        model="gemini-2.5-flash",
        instruction=(
            "Eres el responsable de releases. Llama a next_version y a parse_commits "
            "con la versión y los commits que te den; no calcules la versión tú. "
            "Responde con la versión nueva, por qué ese salto y las notas agrupadas."
        ),
        tools=[FunctionTool(func=next_version), FunctionTool(func=parse_commits)],
    )
    return App(name="release_manager", root_agent=agente)


async def main() -> None:
    runner = InMemoryRunner(app=construir())
    await runner.session_service.create_session(
        app_name=runner.app_name, user_id="demo", session_id="demo-1"
    )
    mensaje = types.Content(
        role="user",
        parts=[types.Part.from_text(text="Versión actual: 1.4.2.\nfeat(api): paginación en /orders\nfix: cierre de conexiones al reiniciar")],
    )
    async for evento in runner.run_async(
        user_id="demo", session_id="demo-1", new_message=mensaje
    ):
        if evento.content and evento.content.parts:
            for parte in evento.content.parts:
                if getattr(parte, "text", None):
                    print(parte.text, end="", flush=True)
    print()


if __name__ == "__main__":
    asyncio.run(main())
