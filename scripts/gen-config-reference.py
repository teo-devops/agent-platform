#!/usr/bin/env python3
"""Genera docs/configuration.md desde los modelos.

La referencia de campos es lo primero que se desfasa cuando se escribe a mano: se
añade un campo, se olvida la tabla, y seis meses después la documentación miente.
Aquí se genera del mismo sitio del que sale el JSON Schema, y `make test`
comprueba que está al día.

Uso:  python3 scripts/gen-config-reference.py [-o docs/configuration.md] [--check]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
SALIDA = RAIZ / "docs" / "configuration.md"

CABECERA = """# Referencia de configuración

> GENERADO desde los modelos de `agent-core`. No lo edites a mano: cambia el
> modelo y ejecuta `make docs`. Si esta página se desfasa, `make test` falla.

Un manifiesto se escribe una vez y lo ejecutan los tres runtimes. Nada de lo que
hay aquí nombra un framework, salvo `spec.runtime`, que es precisamente el
interruptor para elegirlo.

Dos formas del mismo documento: la que **escribes** puede dejar cosas implícitas
(`type: sequential` en vez de escribir cada `needs`), y la que se **publica** con
`agentctl export` las deja todas escritas. Mismo `kind`, mismo esquema.

Las capas de configuración, de menor a mayor prioridad:

```
configs/defaults.yaml              -> toda la flota
configs/environments/<env>.yaml    -> ese entorno
catalog/agents/<dominio>/<nombre>/agent.yaml -> lo que pide el agente
configs/environments/<env>.yaml    -> agents.<nombre>, un retoque puntual
```
"""


def cargar_modelos() -> dict:
    sys.path.insert(0, str(RAIZ / "platform" / "agent-core" / "src"))
    from agent_core.schemas import AgentManifest, WorkflowManifest

    return {"Agent": AgentManifest, "Workflow": WorkflowManifest}


def tipo_de(prop: dict, defs: dict) -> str:
    """Nombre legible del tipo de un campo."""
    if "$ref" in prop:
        nombre = prop["$ref"].split("/")[-1]
        return f"[`{nombre}`](#{nombre.lower()})"
    if "const" in prop:
        return f"`{prop['const']}`"
    if "enum" in prop:
        return " \\| ".join(f"`{v}`" for v in prop["enum"])
    if "anyOf" in prop:
        partes = [tipo_de(p, defs) for p in prop["anyOf"] if p.get("type") != "null"]
        return " \\| ".join(dict.fromkeys(partes)) or "`null`"
    if prop.get("type") == "array":
        return f"lista de {tipo_de(prop.get('items', {}), defs)}"
    if prop.get("type") == "object":
        extra = prop.get("additionalProperties")
        if isinstance(extra, dict):
            return f"mapa de {tipo_de(extra, defs)}"
        return "mapa"
    return f"`{prop.get('type', 'any')}`"


# Resumen en castellano de cada bloque. El docstring del modelo está en inglés,
# como el resto del código; la documentación del repositorio está en castellano.
RESUMENES = {
    "AgentManifest": "Un agente. Es la unidad que se ejecuta y la que se referencia desde un flujo.",
    "WorkflowManifest": "Un flujo: varios agentes compuestos en una tubería determinista.",
    "AgentBody": "Todo lo que se puede cambiar de un agente sin tocar código.",
    "WorkflowBody": "La forma del flujo y lo que se aplica a todos sus pasos.",
    "Metadata": "Quién es este manifiesto. El `name` es la referencia que se usa en todas partes.",
    "ModelSpec": "Qué modelo responde y con qué ajustes de generación.",
    "PromptSpec": "Las instrucciones del agente: en línea o en un fichero aparte.",
    "ToolRef": "Una herramienta registrada que el agente puede llamar.",
    "SkillRef": "Una skill del catálogo. Sólo su descripción viaja en el prompt; el cuerpo lo pide el agente.",
    "SubAgentRef": "Cómo se engancha otro agente a este.",
    "GuardrailsSpec": "Guardrails agrupados por el momento en que se aplican.",
    "GuardrailRule": "Una comprobación sobre un texto.",
    "PolicySpec": "Cuánto trabajo puede hacer una invocación. Lo aplica el runtime, no se le pide al modelo.",
    "BudgetSpec": "Techos de coste de una invocación.",
    "PermissionSpec": "Qué puede alcanzar. Se comprueba al construir y otra vez al llamar.",
    "AllowDeny": "Listas de patrones. `deny` gana siempre sobre `allow`.",
    "PluginRef": "Un plugin extra, más allá de los que se derivan de las secciones anteriores.",
    "NodeSpec": "Un paso del flujo: un agente con un nombre dentro de la tubería.",
    "EdgeSpec": "Una arista dirigida entre dos pasos.",
    "InputSpec": "Un parámetro de entrada del flujo.",
    "EvalSpec": "Puerta de calidad sobre el resultado del flujo.",
}


def por_defecto(nombre: str, prop: dict, obligatorios: list[str]) -> str:
    if nombre in obligatorios:
        return "**obligatorio**"
    if "default" not in prop:
        # `default_factory` no llega al JSON Schema, pero el campo es opcional.
        return "—"
    valor = prop["default"]
    if valor in (None, "", [], {}):
        return "—"
    return f"`{valor}`"


def tabla(nombre: str, definicion: dict, defs: dict) -> str:
    lineas = [f"### `{nombre}`", ""]
    resumen = RESUMENES.get(nombre)
    if resumen:
        lineas += [resumen, ""]

    propiedades = definicion.get("properties", {})
    if not propiedades:
        return "\n".join(lineas + [""])

    obligatorios = definicion.get("required", [])
    lineas += ["| campo | tipo | por defecto | qué hace |", "|---|---|---|---|"]
    for campo, prop in propiedades.items():
        descripcion = (prop.get("description") or "").strip().replace("\n", " ").replace("|", "\\|")
        lineas.append(
            f"| `{campo}` | {tipo_de(prop, defs)} | {por_defecto(campo, prop, obligatorios)} | {descripcion} |"
        )
    return "\n".join(lineas + [""])


def referencias(prop: dict) -> list[str]:
    if "$ref" in prop:
        return [prop["$ref"].split("/")[-1]]
    encontradas: list[str] = []
    for clave in ("anyOf", "oneOf"):
        for sub in prop.get(clave, []):
            encontradas += referencias(sub)
    for clave in ("items", "additionalProperties"):
        sub = prop.get(clave)
        if isinstance(sub, dict):
            encontradas += referencias(sub)
    return encontradas


def ordenar(schema: dict, defs: dict) -> list[str]:
    """Bloques alcanzables desde un manifiesto, en anchura."""
    pendientes = [schema]
    orden: list[str] = []
    while pendientes:
        actual = pendientes.pop(0)
        for prop in actual.get("properties", {}).values():
            for referencia in referencias(prop):
                if referencia not in orden and referencia in defs:
                    orden.append(referencia)
                    pendientes.append(defs[referencia])
    return orden


def generar() -> str:
    partes = [CABECERA]
    vistos: set[str] = set()

    for kind, modelo in cargar_modelos().items():
        schema = modelo.model_json_schema(by_alias=True, mode="serialization")
        defs = schema.get("$defs", {})

        partes.append(f"\n---\n\n## `kind: {kind}`\n")
        partes.append(tabla(f"{kind}Manifest", schema, defs))

        for nombre in ordenar(schema, defs):
            if nombre in vistos:
                continue
            vistos.add(nombre)
            partes.append(tabla(nombre, defs[nombre], defs))

    return "\n".join(partes)


def main() -> int:
    parser = argparse.ArgumentParser(description="Genera la referencia de configuración.")
    parser.add_argument("-o", "--output", default=str(SALIDA))
    parser.add_argument("--check", action="store_true", help="Sólo comprobar si está al día")
    args = parser.parse_args()

    contenido = generar()
    destino = Path(args.output)

    if args.check:
        actual = destino.read_text(encoding="utf-8") if destino.exists() else ""
        if actual != contenido:
            print(f"{destino} está desfasado. Regenéralo con 'make docs'.", file=sys.stderr)
            return 1
        print(f"{destino} está al día.")
        return 0

    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(contenido, encoding="utf-8")
    print(f"✓ {destino}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
