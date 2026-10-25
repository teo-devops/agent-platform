"""Las fronteras entre paquetes, comprobadas en vez de prometidas."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLATFORM = ROOT / "platform"


def _imports(pattern: str) -> list[Path]:
    regex = re.compile(rf"^\s*(from|import)\s+{pattern}\b", re.M)
    return [p for p in PLATFORM.rglob("*.py") if regex.search(p.read_text(encoding="utf-8"))]


def test_only_the_mlflow_integration_imports_mlflow():
    offenders = [p for p in _imports("mlflow") if "integrations/mlflow" not in p.as_posix()]
    assert not offenders, f"importan mlflow fuera de integrations/mlflow: {offenders}"


def test_core_imports_no_framework():
    core = PLATFORM / "core"
    for framework in ("google.adk", "langgraph", "langchain", "kagent", "mcp", "mlflow"):
        offenders = [p for p in _imports(re.escape(framework)) if core in p.parents]
        assert not offenders, f"agent-core importa {framework}: {offenders}"


def test_only_the_kagent_package_imports_kagent():
    offenders = [p for p in _imports("kagent") if "platform/kagent" not in p.as_posix()]
    assert not offenders, offenders


def test_only_the_a2a_package_speaks_a2a():
    """Los builders piden un delegado a la fábrica; el protocolo vive en un sitio."""
    for module in ("a2a", "httpx"):
        offenders = [p for p in _imports(module) if "platform/a2a" not in p.as_posix()]
        assert not offenders, f"importan {module} fuera de platform/a2a: {offenders}"


def test_core_knows_no_sandbox_backend():
    """El core define qué se aísla; cómo lo hace cada backend vive en platform/sandboxes/."""
    core = PLATFORM / "core"
    for backend in ("agent_sandbox_", "docker", "openshell"):
        offenders = [p for p in _imports(re.escape(backend) + r"\w*") if core in p.parents]
        assert not offenders, f"agent-core importa {backend}: {offenders}"


def test_only_sandbox_backends_shell_out_to_docker():
    offenders = [
        p for p in PLATFORM.rglob("*.py")
        if '"docker"' in p.read_text(encoding="utf-8") and "platform/sandboxes/" not in p.as_posix()
    ]
    assert not offenders, f"llaman a docker fuera de platform/sandboxes: {offenders}"
