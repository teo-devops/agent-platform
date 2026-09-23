"""The agentctl surface, exercised without touching a model."""

from __future__ import annotations

import pytest
from agent_runtime.cli import main


@pytest.fixture(autouse=True)
def _root_env(root, monkeypatch):
    monkeypatch.setenv("AGENT_PLATFORM_ROOT", str(root))
    monkeypatch.setenv("AGENT_ENV", "local")


def test_list_prints_agents_and_workflows(capsys):
    assert main(["list"]) == 0
    output = capsys.readouterr().out
    assert "health-advisor" in output
    assert "research-and-write" in output


def test_show_prints_the_resolved_configuration(capsys):
    assert main(["show", "health-advisor"]) == 0
    output = capsys.readouterr().out
    assert "gemini-2.5-flash" in output
    assert "health.calculate_bmi" in output


def test_validate_reports_every_manifest(capsys):
    assert main(["validate"]) == 0
    assert "valid in environment 'local'" in capsys.readouterr().out


def test_components_lists_installed_extensions(capsys):
    assert main(["components"]) == 0
    output = capsys.readouterr().out
    assert "health.calculate_bmi" in output
    assert "workflow" in output


def test_show_reports_unknown_names(capsys):
    assert main(["show", "nope"]) == 2
    assert "neither a known agent" in capsys.readouterr().err
