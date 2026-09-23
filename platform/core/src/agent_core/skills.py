"""Skills: instrucciones reutilizables que un agente carga cuando le hacen falta.

Una skill es una carpeta con un ``SKILL.md`` —frontmatter con `name`,
`version`, `description` y `when_to_use`, y un cuerpo con las instrucciones— más
`references/` y `scripts/` opcionales. Es el formato que se ha estandarizado, y
se eligió por encima de inventar otro para poder usar skills de fuera y publicar
las propias.

La idea que lo hace viable es la **divulgación progresiva**. Meter el cuerpo de
cada skill en el system prompt es lo obvio y lo caro: tres skills de 2.000
tokens son 6.000 tokens en *cada* llamada, se pague o no se use ninguna. Así que:

* al construir, sólo viajan el nombre, la descripción y el cuándo usarla,
* y el cuerpo se sirve con una herramienta, ``skill.read``, cuando el agente
  decide que le hace falta.

Eso funciona igual en los tres runtimes sin escribir nada específico de ninguno,
porque por debajo no es más que otra herramienta.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .errors import ConfigError

SKILL_FILE = "SKILL.md"

_FRONTMATTER = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", re.DOTALL)
_REF = re.compile(r"^(?P<name>[a-z0-9][a-z0-9-]*)(?:@(?P<range>[\^~]?[0-9][0-9.]*))?$")


@dataclass(frozen=True)
class Skill:
    """Una skill cargada del catálogo."""

    name: str
    version: str
    description: str
    when_to_use: str
    body: str
    path: Path
    references: list[str] = field(default_factory=list)
    scripts: list[str] = field(default_factory=list)

    @property
    def summary(self) -> str:
        """Lo único que viaja siempre en el prompt."""
        linea = f"- **{self.name}** (v{self.version}): {self.description}"
        if self.when_to_use:
            linea += f" Úsala cuando: {self.when_to_use}"
        return linea

    def read(self) -> str:
        """El cuerpo, más el índice de lo que puede abrir a continuación."""
        partes = [self.body.strip()]
        if self.references:
            partes.append(
                "## Material de referencia\n\n"
                + "\n".join(f"- `{nombre}`" for nombre in self.references)
                + "\n\nÁbrelo con skill_open(skill, referencia)."
            )
        if self.scripts:
            partes.append(
                "## Scripts incluidos\n\n"
                + "\n".join(f"- `{nombre}`" for nombre in self.scripts)
            )
        return "\n\n".join(partes)

    def open(self, reference: str) -> str:
        """Un fichero de ``references/``, bajo demanda."""
        if reference not in self.references:
            raise ConfigError(
                f"skill '{self.name}' no tiene la referencia '{reference}'. "
                f"Tiene: {', '.join(self.references) or '<ninguna>'}"
            )
        return (self.path / "references" / reference).read_text(encoding="utf-8")


def load_skill(directory: Path) -> Skill:
    """Lee un ``SKILL.md`` y lo que lo acompaña."""
    archivo = directory / SKILL_FILE
    if not archivo.exists():
        raise ConfigError(f"{directory} no es una skill: falta {SKILL_FILE}")

    texto = archivo.read_text(encoding="utf-8")
    encontrado = _FRONTMATTER.match(texto)
    if not encontrado:
        raise ConfigError(
            f"{archivo}: falta el frontmatter YAML entre '---' con al menos "
            f"name y description."
        )

    try:
        meta = yaml.safe_load(encontrado.group(1)) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"{archivo}: frontmatter inválido: {exc}") from exc

    if not isinstance(meta, dict) or "name" not in meta:
        raise ConfigError(f"{archivo}: el frontmatter necesita al menos 'name'")

    nombre = str(meta["name"])
    if nombre != directory.name:
        raise ConfigError(
            f"{archivo}: name '{nombre}' no coincide con la carpeta '{directory.name}'"
        )

    descripcion = str(meta.get("description", "")).strip()
    if not descripcion:
        raise ConfigError(
            f"{archivo}: 'description' es obligatoria. Es lo único que el agente "
            f"ve siempre, así que es lo que decide si la skill llega a usarse."
        )

    return Skill(
        name=nombre,
        version=str(meta.get("version", "0.1.0")),
        description=descripcion,
        when_to_use=str(meta.get("when_to_use", "")).strip(),
        body=encontrado.group(2),
        path=directory,
        references=sorted(p.name for p in (directory / "references").glob("*") if p.is_file()),
        scripts=sorted(p.name for p in (directory / "scripts").glob("*.py")),
    )


def satisfies(version: str, rango: str | None) -> bool:
    """¿Cumple ``version`` el rango pedido? ``^1.2`` compatible, ``~1.2`` menor, exacto."""
    if not rango:
        return True

    operador, pedido = (rango[0], rango[1:]) if rango[0] in "^~" else ("", rango)
    actual = [int(p) for p in version.split(".") if p.isdigit()]
    objetivo = [int(p) for p in pedido.split(".") if p.isdigit()]
    actual += [0] * (3 - len(actual))

    if operador == "^":  # mismo major, y al menos lo pedido
        return actual[0] == objetivo[0] and actual >= objetivo + [0] * (3 - len(objetivo))
    if operador == "~":  # mismo major.minor
        return actual[: len(objetivo)] == objetivo or (
            len(objetivo) >= 2 and actual[:2] == objetivo[:2] and actual >= objetivo + [0]
        )
    return actual[: len(objetivo)] == objetivo


def parse_ref(ref: str) -> tuple[str, str | None]:
    """``hexagonal-architecture@^1.0`` -> ``("hexagonal-architecture", "^1.0")``."""
    encontrado = _REF.match(ref)
    if not encontrado:
        raise ConfigError(
            f"referencia de skill inválida: '{ref}'. Se espera 'nombre' o 'nombre@rango'."
        )
    return encontrado.group("name"), encontrado.group("range")


class SkillSet:
    """Las skills enganchadas a un agente, y las herramientas que las sirven."""

    def __init__(self, skills: list[Skill]) -> None:
        self.skills = {skill.name: skill for skill in skills}

    def __bool__(self) -> bool:
        return bool(self.skills)

    def prompt_section(self) -> str:
        """Lo que se añade al system prompt: sólo el índice, nunca el cuerpo."""
        if not self.skills:
            return ""
        lineas = [skill.summary for skill in self.skills.values()]
        return (
            "\n\n## Skills disponibles\n\n"
            + "\n".join(lineas)
            + "\n\nCada una es un conjunto de instrucciones que todavía NO has leído. "
            "Cuando una encaje con lo que te piden, llama a skill_read con su nombre "
            "ANTES de responder, y sigue lo que diga."
        )

    # -- las herramientas ---------------------------------------------------

    def read(self, skill: str) -> dict[str, Any]:
        """Reads the full instructions of one of the skills available to you.

        Args:
            skill: Name of the skill, exactly as listed in "Skills disponibles".

        Returns:
            A dict with the instructions to follow.
        """
        encontrada = self.skills.get(skill)
        if encontrada is None:
            return {
                "error": f"unknown skill '{skill}'",
                "available": sorted(self.skills),
            }
        return {"skill": skill, "instructions": encontrada.read()}

    def open(self, skill: str, reference: str) -> dict[str, Any]:
        """Opens one reference file of a skill you have already read.

        Args:
            skill: Name of the skill the reference belongs to.
            reference: File name, as listed by skill.read.

        Returns:
            A dict with the contents of the file.
        """
        encontrada = self.skills.get(skill)
        if encontrada is None:
            return {"error": f"unknown skill '{skill}'", "available": sorted(self.skills)}
        try:
            return {"skill": skill, "reference": reference, "content": encontrada.open(reference)}
        except ConfigError as exc:
            return {"error": str(exc)}

    def as_tools(self) -> dict[str, Any]:
        """Las funciones que cada runtime envolverá a su manera.

        Se construyen aquí, con nombre propio, porque los tres frameworks
        derivan el nombre de la herramienta de ``__name__`` y un método
        enlazado se llamaría ``read``, que choca con cualquier tool de usuario
        que se llame igual.

        **No pasan por `permissions.tools` a propósito.** Esas listas controlan
        lo que un agente alcanza del mundo; leer las instrucciones que él mismo
        declaró en `spec.skills` no es alcanzar nada. Declarar la skill ES el
        permiso, y exigir además una entrada en la lista sería contabilidad
        doble: engancharías una skill, olvidarías el permiso, y el agente se
        quedaría sin poder leerla sin que nadie dijera nada.
        """
        if not self.skills:
            return {}

        conjunto = self

        def skill_read(skill: str) -> dict[str, Any]:
            """Reads the full instructions of one of the skills available to you.

            Args:
                skill: Name of the skill, exactly as listed in "Skills disponibles".

            Returns:
                A dict with the instructions to follow.
            """
            return conjunto.read(skill)

        def skill_open(skill: str, reference: str) -> dict[str, Any]:
            """Opens one reference file of a skill you have already read.

            Args:
                skill: Name of the skill the reference belongs to.
                reference: File name, as listed by skill_read.

            Returns:
                A dict with the contents of the file.
            """
            return conjunto.open(skill, reference)

        herramientas = {"skill_read": skill_read}
        if any(skill.references for skill in self.skills.values()):
            herramientas["skill_open"] = skill_open
        return herramientas
