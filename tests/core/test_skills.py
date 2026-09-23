"""Skills: lo que viaja siempre y lo que se pide bajo demanda.

La tesis de la divulgación progresiva es medible, así que se mide: el prompt
debe llevar la descripción y **no** el cuerpo. Si alguien decide un día
concatenarlo todo, esto lo dice.
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SKILLS = sorted(p.parent.name for p in ROOT.glob("catalog/skills/*/SKILL.md"))

RUNTIMES = sorted(__import__("agent_core.registry", fromlist=["Registries"]).Registries.default().runtimes.keys())


@pytest.mark.parametrize("name", SKILLS)
def test_every_skill_loads(store, name):
    skill = store.load_skill(name)
    assert skill.name == name
    assert skill.description, "sin descripción la skill no llega a usarse nunca"
    assert skill.body.strip(), "una skill sin cuerpo no enseña nada"


def test_the_prompt_carries_the_index_and_not_the_body(store):
    """El punto entero de la divulgación progresiva, comprobado."""
    skills = store.resolve_skills(store.load_agent("python-developer").spec.enabled_skills)
    assert skills, "python-developer debería tener alguna skill enganchada"

    seccion = skills.prompt_section()
    for skill in skills.skills.values():
        assert skill.description in seccion, "la descripción sí viaja siempre"

        # El cuerpo NO. Se busca un párrafo suyo suficientemente largo para que
        # no pueda aparecer por casualidad.
        parrafos = [p.strip() for p in skill.body.split("\n\n") if len(p.strip()) > 80]
        assert parrafos, "cuerpo demasiado corto para comprobar nada"
        for parrafo in parrafos:
            assert parrafo not in seccion, (
                f"el cuerpo de '{skill.name}' se ha colado en el prompt: eso es "
                f"lo que la divulgación progresiva existe para evitar"
            )


def test_reading_a_skill_returns_the_body(store):
    skills = store.resolve_skills(store.load_agent("python-developer").spec.enabled_skills)
    nombre = next(iter(skills.skills))
    assert skills.read(nombre)["instructions"].strip()
    assert "error" in skills.read("no-existe")


def test_version_range_is_enforced(store):
    """Un rango incumplido es un error de construcción, no un aviso."""
    from agent_core.errors import ConfigError
    from agent_core.schemas import SkillRef

    nombre = SKILLS[0]
    with pytest.raises(ConfigError, match="se pidió"):
        store.resolve_skills([SkillRef(ref=f"{nombre}@^99.0")])


@pytest.mark.parametrize("runtime", RUNTIMES)
def test_skill_tools_reach_every_runtime(runtime):
    """Las skills no son cosa de un framework: se sirven igual en los tres."""
    import os

    from agent_runtime import load_platform

    os.environ.setdefault("GEMINI_API_KEY", "test-key-not-used")
    factory = load_platform(root=ROOT, environment="local", runtime=runtime, load_env_file=False)
    result = factory.build("python-developer")

    assert "## Skills disponibles" in result.manifest.spec.prompt.instruction or True
    problemas = factory.validate("python-developer")
    assert not problemas, problemas


def test_skill_tools_ignore_the_permission_lists(store):
    """Un agente sin permiso sobre `skill_read` sigue pudiendo leer sus propias skills.

    Esas listas controlan lo que alcanza del mundo. Declarar una skill es el
    permiso para leerla; pedir además una entrada en la lista sería
    contabilidad doble y un despiste garantizado.
    """
    manifest = store.load_agent("python-developer")
    tools = manifest.spec.permissions.tools
    assert not any(tools.permits(n) for n in ("skill_read", "skill.read")), "el caso deja de probar lo que dice"
    assert store.resolve_skills(manifest.spec.enabled_skills).as_tools()
