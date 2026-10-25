"""El backend `openshell`: la política que genera, el CLI simulado y, si se pide, un gateway real."""

from __future__ import annotations

import os
import shutil

import pytest
import yaml
from agent_core.errors import ConfigError
from agent_core.sandbox import LazySandbox, SandboxError, sandbox_tools
from agent_core.schemas import PermissionSpec, SandboxSpec

pytest.importorskip("agent_sandbox_openshell")
from agent_sandbox_openshell import OpenShellSandbox, create_args, render_policy, warnings  # noqa: E402

from . import fake_cli  # noqa: E402


def _spec(**overrides) -> SandboxSpec:
    return SandboxSpec(backend="openshell", **overrides)


def test_the_policy_is_version_1_with_landlock_required_and_no_root():
    policy = render_policy(_spec())
    assert policy["version"] == 1
    assert policy["landlock"] == {"compatibility": "hard_requirement"}
    assert policy["process"] == {"run_as_user": "1000", "run_as_group": "1000"}
    assert "network_policies" not in policy, "sin reglas, OpenShell lo deniega todo"


def test_filesystem_is_the_spec_plus_what_a_process_needs():
    fs = render_policy(_spec())["filesystem_policy"]
    assert fs["read_write"][0] == "/workspace" and "/tmp" in fs["read_write"]
    assert "/usr" in fs["read_only"] and "/workspace" not in fs["read_only"]
    assert fs["include_workdir"] is False
    assert len(set(fs["read_only"])) == len(fs["read_only"])


def test_each_allowed_host_is_a_network_rule():
    rules = render_policy(_spec(network={"egress": {"allow": ["pypi.org", "github.com:22"]}}))["network_policies"]
    endpoints = {r["endpoints"][0]["host"]: r["endpoints"][0]["port"] for r in rules.values()}
    assert endpoints == {"pypi.org": 443, "github.com": 22}
    assert all(r["binaries"] for r in rules.values()), "binaries vacío no casa con nada"


@pytest.mark.parametrize(
    ("spec", "error"),
    [
        ({"network": {"egress": {"default": "allow"}}}, "cannot be expressed"),
        ({"inference": {"route": "direct"}}, "credentials inside"),
        ({"network": {"egress": {"allow": ["*.com"]}}}, "three DNS labels"),
    ],
)
def test_what_would_weaken_the_sandbox_is_refused(spec, error):
    with pytest.raises(ConfigError, match=error):
        render_policy(_spec(**spec))


def test_what_has_no_policy_field_is_said_out_loud():
    found = " ".join(warnings(_spec(process={"max_procs": 8}, resources={"memory": "1Gi"})))
    assert "max_procs" in found and "cpu/memory" in found


def test_create_uses_the_policy_the_image_and_a_provider_only_for_platform(monkeypatch):
    monkeypatch.setenv("AGENT_OPENSHELL_PROVIDER", "nvidia")
    args = create_args(_spec(inference={"route": "platform"}), name="ap-x", policy_file="/p.yaml")
    assert args[args.index("--policy") + 1] == "/p.yaml"
    assert args[args.index("--provider") + 1] == "nvidia"
    assert "--provider" not in create_args(_spec(), name="ap-x", policy_file="/p.yaml")
    assert args[-3:-1] == ["--", "sleep"]


def test_the_session_creates_with_the_policy_runs_and_deletes(tmp_path, monkeypatch):
    log, root = fake_cli.install(tmp_path, "openshell")
    monkeypatch.setenv("PATH", fake_cli.path_with(tmp_path))
    sandbox = LazySandbox(_spec(), OpenShellSandbox(), agent="probe")
    tools = sandbox_tools(sandbox, PermissionSpec())

    tools["sandbox.write_file"]("src/a.py", "print('hola')")
    assert (root / "src" / "a.py").exists()
    result = tools["sandbox.exec"]("echo dentro; exit 4")
    assert (result["exit_code"], result["stdout"].strip()) == (4, "dentro")
    sandbox.close()

    sent = yaml.safe_load((tmp_path / "calls.jsonl.policy").read_text())
    assert sent == render_policy(_spec()), "el sandbox se crea con la política que se audita"
    calls = fake_cli.calls(log)
    assert calls[0] == ["status"]
    name = next(c[c.index("--name") + 1] for c in calls if c[:2] == ["sandbox", "create"])
    assert ["sandbox", "delete", name] in calls


def test_a_sandbox_that_fails_to_start_is_reported_and_removed(tmp_path, monkeypatch):
    log, _ = fake_cli.install(tmp_path, "openshell")
    monkeypatch.setenv("PATH", fake_cli.path_with(tmp_path))
    monkeypatch.setenv("FAKE_OPENSHELL_PHASE", "Error")
    with pytest.raises(SandboxError, match="ended as 'error'"):
        OpenShellSandbox().open(_spec(), agent="probe")
    assert any(c[:2] == ["sandbox", "delete"] for c in fake_cli.calls(log))


def test_without_the_cli_the_error_says_how_to_install(monkeypatch, tmp_path):
    monkeypatch.setenv("PATH", str(tmp_path))
    with pytest.raises(SandboxError, match="install.sh"):
        OpenShellSandbox().open(_spec(), agent="probe")


@pytest.mark.skipif(
    os.getenv("AGENT_SANDBOX_OPENSHELL_TESTS") != "1" or shutil.which("openshell") is None,
    reason="gateway real de OpenShell: AGENT_SANDBOX_OPENSHELL_TESTS=1",
)
def test_a_real_openshell_sandbox_runs_code_under_its_policy():
    sandbox = LazySandbox(_spec(resources={"command_timeout_seconds": 60}), OpenShellSandbox(), agent="pytest")
    try:
        tools = sandbox_tools(sandbox, PermissionSpec())
        assert tools["sandbox.run_python"]("print(6 * 7)")["stdout"].strip() == "42"
        offline = tools["sandbox.run_python"](
            "import urllib.request\n"
            "try:\n    urllib.request.urlopen('https://pypi.org', timeout=8)\n    print('online')\n"
            "except Exception:\n    print('offline')"
        )
        assert offline["stdout"].strip() == "offline"
        assert tools["sandbox.exec"]("touch /usr/x")["exit_code"] != 0, "Landlock: /usr es de sólo lectura"
    finally:
        sandbox.close()
