"""El contrato: un solo vocabulario, generado desde los modelos.

No hay traducción entre planos. Quien consume un manifiesto de este repositorio
lee el mismo `kind` y el mismo `apiVersion` que escribe quien lo desarrolla. Lo
único que cambia es que la forma publicada no deja nada implícito.

Estos tests cubren las dos mitades de esa afirmación: que el esquema publicado
sigue siendo el de los modelos, y que la forma resuelta es correcta.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CONTRACTS_DIR = Path(
    os.environ.get("AGENTIC_CONTRACTS_DIR", ROOT.parent / "genai-platform" / "contracts")
)

PINNED = r"^[a-z0-9-]+@[0-9]+\.[0-9]+\.[0-9]+$"


def _names(kind: str) -> list[str]:
    if kind == "Agent":
        return sorted(p.parent.name for p in ROOT.glob("catalog/agents/*/*/agent.yaml"))
    return sorted(p.stem for p in ROOT.glob("catalog/workflows/*.yaml"))


AGENTS = _names("Agent")
WORKFLOWS = _names("Workflow")


@pytest.fixture(scope="module")
def schemas() -> dict:
    from agent_core.schemas import AgentManifest, WorkflowManifest

    return {
        "Agent": AgentManifest.model_json_schema(by_alias=True, mode="serialization"),
        "Workflow": WorkflowManifest.model_json_schema(by_alias=True, mode="serialization"),
    }


@pytest.mark.parametrize("name", AGENTS + WORKFLOWS)
def test_every_manifest_resolves(store, name):
    """Nada de lo que hay en el repositorio debe quedarse sin poder publicarse."""
    from agent_core.publish import resolve

    resolved = resolve(store.load(name), store)
    assert resolved.document["apiVersion"] == "agents.platform/v1"
    assert resolved.name == name


@pytest.mark.parametrize("name", AGENTS + WORKFLOWS)
def test_resolved_manifest_validates_against_its_own_schema(store, schemas, name):
    """La forma resuelta y la escrita a mano cumplen el MISMO esquema.

    Es lo que hace que no haya dos dialectos: publicar no cambia de vocabulario,
    sólo rellena lo que el autor podía dejar implícito.
    """
    import jsonschema

    from agent_core.publish import resolve

    resolved = resolve(store.load(name), store)
    jsonschema.validate(instance=resolved.document, schema=schemas[resolved.kind])


@pytest.mark.parametrize("name", WORKFLOWS)
def test_resolved_workflow_pins_and_orders(store, name):
    """Sin versión exacta no es reproducible; sin `needs` no es programable."""
    import re

    from agent_core.publish import resolve

    spec = resolve(store.load(name), store).document["spec"]
    nodes = spec["nodes"]

    for node in nodes:
        assert re.match(PINNED, node["agent"]), (
            f"{name}: el paso '{node['name']}' referencia '{node['agent']}' sin SemVer exacta"
        )
        assert node["with"], f"{name}: el paso '{node['name']}' no declara de dónde lee"

    assert spec["inputs"], f"{name}: un flujo publicado debe declarar sus entradas"

    if spec["type"] == "sequential" and len(nodes) > 1:
        assert nodes[1]["needs"] == [nodes[0]["name"]], (
            f"{name}: el orden secuencial no sobrevivió a la publicación"
        )


def test_author_written_needs_are_respected(store):
    """Si alguien escribe `needs` a mano, publicar no debe reescribirlo."""
    from agent_core.publish import dependencies
    from agent_core.schemas import WorkflowBody

    body = WorkflowBody(
        type="sequential",
        nodes=[
            {"name": "a", "agent": "researcher"},
            {"name": "b", "agent": "writer"},
            {"name": "c", "agent": "greeting", "needs": ["a"]},
        ],
    )
    assert dependencies(body) == {"a": [], "b": [], "c": ["a"]}


@pytest.mark.skipif(
    not CONTRACTS_DIR.exists(),
    reason=f"el plano plataforma no está en {CONTRACTS_DIR}; "
           f"apunta AGENTIC_CONTRACTS_DIR a un checkout de genai-platform",
)
@pytest.mark.parametrize("kind", ["Agent", "Workflow"])
def test_published_schema_is_up_to_date(schemas, kind):
    """El esquema que consume el otro plano tiene que ser el de estos modelos.

    Si falla, alguien cambió un modelo y no regeneró:  make schema
    """
    published = CONTRACTS_DIR / "schemas" / f"{kind.lower()}.schema.json"
    assert published.exists(), f"falta {published}: genéralo con 'agentctl schema'"

    stored = json.loads(published.read_text(encoding="utf-8"))
    for generated_only in ("$schema", "title", "description"):
        stored.pop(generated_only, None)

    current = dict(schemas[kind])
    for generated_only in ("$schema", "title", "description"):
        current.pop(generated_only, None)

    assert stored == current, (
        f"el esquema publicado de {kind} está desfasado respecto a los modelos. "
        f"Regenéralo:  agentctl schema --kind {kind} -o {CONTRACTS_DIR / 'schemas'}"
    )


def test_configuration_reference_is_up_to_date():
    """La referencia de campos se genera; si se desfasa, esto lo dice.

    Es la garantía de que `docs/configuration.md` no vuelve a mentir: no se
    escribe a mano, sale de los mismos modelos que el esquema.
    """
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "gen-config-reference.py"), "--check"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
