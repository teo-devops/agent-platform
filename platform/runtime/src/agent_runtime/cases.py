"""The use cases of the catalogue, read from ``catalog/cases.yaml``.

A case is a story told with one agent: which one, with what message, in which
environment, and where to look at it. Before this file existed the same facts
lived in the Makefile, the README and the demo script, and drifted. Now `make
caso-N`, `agentctl case`, `agentctl catalog` and the README table all read
them from here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from agent_core.errors import ConfigError

#: Where the cases live, relative to the platform root.
CASES_FILE = Path("catalog") / "cases.yaml"

_FIELDS = {"id", "agent", "summary", "shows", "message", "env", "remote", "requires", "ui", "tip"}


@dataclass(frozen=True)
class Case:
    id: int
    agent: str
    summary: str
    shows: str
    message: str
    env: str | None = None
    #: An A2A URL: the case talks to an agent that already runs there.
    remote: str | None = None
    #: Make targets to run first (images, background processes, port-forwards).
    requires: tuple[str, ...] = field(default_factory=tuple)
    ui: str | None = None
    tip: str | None = None


def load_cases(root: Path) -> list[Case]:
    """Every case, in the order of their ids."""
    path = root / CASES_FILE
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    cases: list[Case] = []
    for entry in data.get("cases") or []:
        unknown = set(entry) - _FIELDS
        if unknown:
            raise ConfigError(f"{CASES_FILE}: caso {entry.get('id')}: campos desconocidos {sorted(unknown)}")
        missing = {"id", "agent", "summary", "shows", "message"} - set(entry)
        if missing:
            raise ConfigError(f"{CASES_FILE}: caso {entry.get('id')}: faltan {sorted(missing)}")
        cases.append(Case(**{**entry, "requires": tuple(entry.get("requires") or ())}))
    ids = [case.id for case in cases]
    if len(ids) != len(set(ids)):
        raise ConfigError(f"{CASES_FILE}: ids repetidos: {ids}")
    return sorted(cases, key=lambda case: case.id)


def find_case(cases: list[Case], case_id: int) -> Case:
    for case in cases:
        if case.id == case_id:
            return case
    raise ConfigError(
        f"no hay caso {case_id}. Casos: {', '.join(str(c.id) for c in cases) or 'ninguno'} "
        f"(los define {CASES_FILE})"
    )


def cases_by_agent(factory: Any, cases: list[Case]) -> dict[str, list[int]]:
    """In which cases each agent takes part: as the one asked, or as a participant.

    ``python-developer`` is never the agent of a case, yet it works in 3, 6 and
    7. The topology says so, so nobody has to keep that list by hand.
    """
    found: dict[str, list[int]] = {}
    for case in cases:
        try:
            agents, _ = factory.participants(case.agent)
        except ConfigError:
            agents = {case.agent: case.agent}
        for name in sorted(set(agents.values())):
            found.setdefault(name, []).append(case.id)
    return found
