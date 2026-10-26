"""catalog/cases.yaml: la única lista de casos, y lo que se construye con ella."""

from __future__ import annotations

import re
from argparse import Namespace
from pathlib import Path

import pytest
from agent_runtime import cli
from agent_runtime.cases import load_cases
from agent_runtime.cli import main


@pytest.fixture(autouse=True)
def _root_env(root, monkeypatch):
    monkeypatch.setenv("AGENT_PLATFORM_ROOT", str(root))
    monkeypatch.setenv("AGENT_ENV", "local")


def _make_targets(root) -> set[str]:
    text = (root / "Makefile").read_text(encoding="utf-8")
    targets = set()
    for line in re.findall(r"^([A-Za-z0-9_.%\- ]+):(?!=)", text, re.M):
        targets.update(line.split())
    return targets


CASES = load_cases(Path(__file__).resolve().parents[2])


def test_ids_are_the_numbers_of_make():
    assert [case.id for case in CASES] == sorted({case.id for case in CASES})
    assert {1, 3, 7, 9, 10} <= {case.id for case in CASES}


@pytest.mark.parametrize("case", CASES, ids=lambda c: f"caso-{c.id}")
def test_every_case_points_at_something_that_exists(case, store, root):
    assert case.agent in [*store.list_agents(), *store.list_workflows()]
    if case.env:
        assert case.env in store.list_environments()
    for target in case.requires:
        assert target in _make_targets(root), f"caso {case.id}: '{target}' no es un target del Makefile"
    assert case.ui, "cada caso dice dónde verlo"


def test_the_makefile_runs_any_case_through_one_rule(root):
    assert "caso-%" in _make_targets(root)
    assert not re.search(r"^caso-\d+\s*:", (root / "Makefile").read_text(encoding="utf-8"), re.M), (
        "un caso escrito a mano en el Makefile: va en catalog/cases.yaml"
    )


def test_case_without_a_number_prints_the_menu(capsys):
    assert main(["case"]) == 0
    output = capsys.readouterr().out
    for case in CASES:
        assert f"make caso-{case.id}" in output


def test_requires_prints_the_make_targets(capsys):
    assert main(["case", "7", "--requires"]) == 0
    assert capsys.readouterr().out.split() == ["a2a-ensure"]


def test_an_unknown_case_is_an_error(capsys):
    assert main(["case", "99"]) == 2
    assert "no hay caso 99" in capsys.readouterr().err


def test_a_case_runs_its_agent_in_its_environment(monkeypatch, capsys):
    seen: list[Namespace] = []
    monkeypatch.setattr(cli, "cmd_run", lambda args: seen.append(args) or 0)
    assert main(["case", "8", "-m", "hola"]) == 0
    (args,) = seen
    assert (args.name, args.env, args.message, args.verbose) == ("data-consumer", "local-a2a", "hola", True)
    output = capsys.readouterr().out
    assert "$ agentctl --env local-a2a run data-consumer -v -m 'hola'" in output
    assert "Míralo también" in output


def test_the_command_line_environment_wins_over_the_case(monkeypatch):
    seen: list[Namespace] = []
    monkeypatch.setattr(cli, "cmd_run", lambda args: seen.append(args) or 0)
    assert main(["--env", "sandbox-sbx", "case", "10"]) == 0
    assert seen[0].env == "sandbox-sbx"


def test_a_remote_case_talks_over_the_transport(monkeypatch, capsys):
    sent = []

    class Delegate:
        def __init__(self, *, name, url):
            self.name, self.url = name, url

        def __call__(self, message):
            sent.append((self.name, self.url, message))
            return "respuesta del pod"

    from agent_core.registry import Registries

    original = Registries.default

    def with_fake_transport():
        registries = original()
        registries.transports.register("a2a", Delegate, override=True)
        return registries

    monkeypatch.setattr(Registries, "default", staticmethod(with_fake_transport))
    assert main(["case", "9"]) == 0
    ((name, url, _),) = sent
    assert name == "software-manager" and "8083/api/a2a/kagent/software-manager" in url
    assert "respuesta del pod" in capsys.readouterr().out


def test_catalog_groups_by_domain_and_says_how_to_try(capsys):
    assert main(["catalog"]) == 0
    output = capsys.readouterr().out
    for domain in ("engineering", "technology", "dataspace", "workflows"):
        assert f"\n{domain}\n" in output
    assert "pruébalo: make caso-3" in output  # software-manager es el agente del caso 3
    assert "casos 3 6 7 9" in output  # python-developer: por la topología, no a mano
    assert "sandbox code-exec" in output
