"""deploy/gitops: lo que ArgoCD lee tiene que existir, estar fijado y estar permitido.

ArgoCD sólo descubre estos errores al sincronizar, en el clúster. Aquí se ven antes.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
GITOPS = ROOT / "deploy" / "gitops"
REPO = "https://github.com/teo-devops/agent-platform.git"
OVERLAYS = ["prod", "lab"]


def _docs(path: Path) -> list[dict]:
    return [d for d in yaml.safe_load_all(path.read_text(encoding="utf-8")) if d]


def _applications() -> list[dict]:
    """Every Application under deploy/gitops, as written (before the overlays patch them)."""
    return [d for p in sorted(GITOPS.rglob("*.yaml")) for d in _docs(p)
            if d.get("kind") == "Application"]


def _sources(app: dict) -> list[dict]:
    spec = app["spec"]
    return spec.get("sources") or [spec["source"]]


PROJECT = _docs(GITOPS / "bootstrap" / "project.yaml")[0]
APPS = _applications()


@pytest.mark.parametrize("app", APPS, ids=lambda a: a["metadata"]["name"])
def test_every_application_stays_inside_the_project(app):
    allowed = set(PROJECT["spec"]["sourceRepos"])
    namespaces = {d["namespace"] for d in PROJECT["spec"]["destinations"]}
    assert app["spec"]["project"] == PROJECT["metadata"]["name"]
    for source in _sources(app):
        assert source["repoURL"] in allowed, f"{source['repoURL']} no está en sourceRepos del AppProject"
    namespace = app["spec"]["destination"].get("namespace")
    assert namespace is None or namespace in namespaces, f"destino {namespace} no permitido"


@pytest.mark.parametrize("app", APPS, ids=lambda a: a["metadata"]["name"])
def test_everything_it_reads_exists_and_is_pinned(app):
    for source in _sources(app):
        if "chart" in source:
            assert re.fullmatch(r"v?\d+\.\d+\.\d+", source["targetRevision"]), "un chart va con versión exacta"
            for values in source.get("helm", {}).get("valueFiles", []):
                assert values.startswith("$values/"), values
                assert (ROOT / values.removeprefix("$values/")).is_file(), f"no existe {values}"
        elif "path" in source:
            assert source["repoURL"] == REPO
            assert (ROOT / source["path"]).is_dir(), f"no existe {source['path']}"
            include = source.get("directory", {}).get("include")
            if include:
                assert (ROOT / source["path"] / include).is_file(), f"no existe {include}"


def test_kagent_matches_the_makefile():
    """`make platform` y ArgoCD instalan el mismo kagent."""
    version = re.search(r"^KAGENT_VERSION \?= (\S+)", (ROOT / "Makefile").read_text(), re.M).group(1)
    charts = {s["chart"]: s["targetRevision"] for a in APPS for s in _sources(a) if "chart" in s}
    assert charts["kagent"] == charts["kagent-crds"] == version


@pytest.mark.parametrize("root", ["root-prod.yaml", "root-lab.yaml"])
def test_the_root_apps_point_at_their_overlay(root):
    app = _docs(GITOPS / "bootstrap" / root)[0]
    overlay = root.removeprefix("root-").removesuffix(".yaml")
    assert app["spec"]["source"]["path"] == f"deploy/gitops/overlays/{overlay}"


def test_no_minio():
    """MinIO está deprecado aquí: los artefactos van a SeaweedFS (deploy/observability)."""
    deploys_minio = re.compile(r"charts\.min\.io|chart:\s*minio|image:\s*\S*minio", re.I)
    offenders = [p for p in (ROOT / "deploy").rglob("*") if p.is_file() and deploys_minio.search(p.read_text(errors="ignore"))]
    assert not offenders, offenders


@pytest.mark.skipif(not shutil.which("kubectl"), reason="kubectl no está instalado")
@pytest.mark.parametrize("overlay", OVERLAYS)
def test_overlays_render(overlay):
    out = subprocess.run(["kubectl", "kustomize", str(GITOPS / "overlays" / overlay)],
                         capture_output=True, text=True, check=True).stdout
    names = {d["metadata"]["name"] for d in yaml.safe_load_all(out) if d}
    assert {"base", "kagent-crds", "observability", "monitoring", "kagent"} <= names


@pytest.mark.skipif(not shutil.which("kubectl"), reason="kubectl no está instalado")
def test_prod_takes_mlflow_from_ghcr_and_exposes_nothing():
    out = subprocess.run(["kubectl", "kustomize", str(GITOPS / "overlays" / "prod")],
                         capture_output=True, text=True, check=True).stdout
    app = next(d for d in yaml.safe_load_all(out) if d and d["metadata"]["name"] == "observability")
    kustomize = app["spec"]["source"]["kustomize"]
    assert any(i.startswith("localhost:5001/agent-platform/mlflow=ghcr.io/") for i in kustomize["images"])
    patched = {p["target"]["kind"] + "/" + p["target"]["name"] for p in kustomize["patches"]}
    assert patched == {"Service/mlflow", "Service/seaweedfs", "Secret/seaweedfs"}
