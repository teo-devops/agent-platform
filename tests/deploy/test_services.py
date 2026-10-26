"""deploy/services.yaml y lo que se construye con él: make status, make down, la tabla de UIs."""

from __future__ import annotations

import importlib.util
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
DATA = yaml.safe_load((ROOT / "deploy" / "services.yaml").read_text(encoding="utf-8"))
SERVICES = DATA["services"]
MAKEFILE = (ROOT / "Makefile").read_text(encoding="utf-8")


def _stack():
    spec = importlib.util.spec_from_file_location("stack", ROOT / "deploy" / "scripts" / "stack.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _targets() -> set[str]:
    found = set()
    for line in re.findall(r"^([A-Za-z0-9_.%\- ]+):(?!=)", MAKEFILE, re.M):
        found.update(line.split())
    return found


@pytest.mark.parametrize("service", SERVICES, ids=lambda s: s["name"])
def test_every_service_says_how_to_start_it_with_a_real_target(service):
    assert service["lane"] in DATA["lanes"]
    assert "url" in service or "a2a" in service
    for field in ("start", "stop", "expose"):
        for command in (c.strip() for c in service.get(field, "").split(" · ") if c.strip()):
            target = command.split()[1]
            assert command.startswith("make ") and target in _targets(), f"{field}: '{command}' no es un target"


def test_what_make_tracks_is_what_status_knows():
    """Cada `$(call TRACK,x)` del Makefile es el `pid` de un servicio, y al revés."""
    tracked = set(re.findall(r"\$\(call TRACK,([\w-]+)\)", MAKEFILE))
    declared = {s["pid"] for s in SERVICES if "pid" in s}
    assert tracked == declared


def test_a2a_services_point_at_an_environment():
    for service in (s for s in SERVICES if "a2a" in s):
        assert (ROOT / "configs" / "environments" / f"{service['a2a']}.yaml").exists()


def test_the_readme_tables_are_up_to_date():
    done = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "gen-readme-tables.py"), "--check"],
        capture_output=True, text=True,
    )
    assert done.returncode == 0, done.stderr


def test_down_stops_what_make_left_running_and_its_children(tmp_path, monkeypatch):
    stack = _stack()
    monkeypatch.setattr(stack, "PIDS", tmp_path)
    monkeypatch.setattr(stack, "load", lambda: {"services": [{"name": "Prueba", "pid": "prueba", "match": "sleep"}]})

    parent = subprocess.Popen(["sh", "-c", "sleep 60 & wait"])
    time.sleep(0.3)
    child = stack._descendants(parent.pid)
    assert child, "el sh debería tener un sleep debajo"
    (tmp_path / "prueba.pid").write_text(f"{parent.pid}\n")

    assert stack.down() == 0
    parent.wait(timeout=5)
    time.sleep(0.2)
    assert not stack._descendants(parent.pid)
    assert not (tmp_path / "prueba.pid").exists()


def test_a_reused_pid_is_not_ours(tmp_path, monkeypatch):
    stack = _stack()
    monkeypatch.setattr(stack, "PIDS", tmp_path)
    (tmp_path / "prueba.pid").write_text(f"{os.getpid()}\n")  # vivo, pero es pytest
    assert stack.tracked("prueba", "agentctl") == []
    assert not (tmp_path / "prueba.pid").exists()


def test_status_works_with_nothing_up(monkeypatch, capsys):
    stack = _stack()
    monkeypatch.setattr(stack, "http_up", lambda url, timeout=1.5: False)
    monkeypatch.setattr(stack, "cluster_mode", lambda: None)
    assert stack.status() == 0
    output = capsys.readouterr().out
    assert "make dev-adk" in output and "make lab" in output
