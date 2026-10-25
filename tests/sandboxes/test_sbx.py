"""El backend `sbx` (Docker Sandboxes): traducción, CLI simulado y, si se pide, una microVM real."""

from __future__ import annotations

import os
import shutil

import pytest
from agent_core.sandbox import LazySandbox, SandboxError, sandbox_tools
from agent_core.schemas import PermissionSpec, SandboxSpec

pytest.importorskip("agent_sandbox_sbx")
from agent_sandbox_sbx import SbxSandbox, create_args, global_allows_all, warnings  # noqa: E402

from . import fake_cli  # noqa: E402

INSPECT = """Rules in this policy:
DECISION   RESOURCE   TYPE               RULE   STATUS
allow      **         network            -      active
allow      **         filesystem:read    -      active
"""


def _spec(**overrides) -> SandboxSpec:
    return SandboxSpec(backend="sbx", **overrides)


def test_deny_by_default_is_a_per_sandbox_deny_rule():
    args = create_args(_spec(), name="ap-x")
    assert args[:3] == ["create", "shell", "--name"]
    assert args[args.index("--deny-network") + 1] == "**"


def test_nothing_of_the_host_is_mounted():
    """Sin ruta: la microVM no ve ningún directorio del host."""
    args = create_args(_spec(), name="ap-x")
    assert not any(a.startswith("/") or a == "." for a in args)


def test_resources_respect_sbx_limits():
    args = create_args(_spec(resources={"cpu": "500m", "memory": "512Mi"}), name="ap-x")
    assert args[args.index("--cpus") + 1] == "1"
    assert args[args.index("-m") + 1] == "1024m"          # sbx no admite menos de 1 GiB
    assert any("1 GiB" in w for w in warnings(_spec(resources={"memory": "512Mi"})))


def test_the_global_allow_all_rule_is_detected():
    assert global_allows_all(INSPECT)
    assert not global_allows_all(INSPECT.replace("allow      **         network", "deny       **         network"))


def test_an_allow_list_is_refused_while_the_global_policy_allows_everything(tmp_path, monkeypatch):
    log, _ = fake_cli.install(tmp_path, "sbx")
    monkeypatch.setenv("PATH", fake_cli.path_with(tmp_path))
    spec = _spec(network={"egress": {"default": "deny", "allow": ["pypi.org"]}})

    with pytest.raises(SandboxError, match="will not do it for you"):
        SbxSandbox().open(spec, agent="probe")
    assert not any(call[0] == "create" for call in fake_cli.calls(log)), "no debe crear nada"


def test_an_allow_list_becomes_per_sandbox_rules_when_it_can(tmp_path, monkeypatch):
    log, _ = fake_cli.install(tmp_path, "sbx")
    monkeypatch.setenv("PATH", fake_cli.path_with(tmp_path))
    monkeypatch.setenv("FAKE_SBX_GLOBAL", "deny       **         network            -      active")
    SbxSandbox().open(_spec(network={"egress": {"default": "deny", "allow": ["pypi.org"]}}), agent="probe")

    allow = [c for c in fake_cli.calls(log) if c[:3] == ["policy", "allow", "network"]]
    assert allow and allow[0][-1] == "pypi.org" and "--sandbox" in allow[0]


def test_the_session_runs_writes_reads_and_removes(tmp_path, monkeypatch):
    log, root = fake_cli.install(tmp_path, "sbx")
    monkeypatch.setenv("PATH", fake_cli.path_with(tmp_path))
    sandbox = LazySandbox(_spec(), SbxSandbox(), agent="probe")
    tools = sandbox_tools(sandbox, PermissionSpec())

    assert tools["sandbox.write_file"]("a.txt", "hola")["path"] == "/workspace/a.txt"
    assert (root / "a.txt").read_text() == "hola"
    assert tools["sandbox.read_file"]("a.txt")["content"] == "hola"
    result = tools["sandbox.exec"]("echo dentro; exit 3")
    assert (result["exit_code"], result["stdout"].strip()) == (3, "dentro")
    sandbox.close()

    names = {c[c.index("--name") + 1] for c in fake_cli.calls(log) if c[0] == "create"}
    assert len(names) == 1 and next(iter(names)).startswith("ap-probe-")
    assert ["rm", "-f", *names] in fake_cli.calls(log)


@pytest.mark.skipif(
    os.getenv("AGENT_SANDBOX_SBX_TESTS") != "1" or shutil.which("sbx") is None,
    reason="microVM real de Docker Sandboxes: AGENT_SANDBOX_SBX_TESTS=1",
)
def test_a_real_microvm_runs_code_with_no_network():
    sandbox = LazySandbox(_spec(resources={"command_timeout_seconds": 60}), SbxSandbox(), agent="pytest")
    try:
        tools = sandbox_tools(sandbox, PermissionSpec())
        assert tools["sandbox.run_python"]("print(6 * 7)")["stdout"].strip() == "42"
        # En sbx el TCP se acepta pero no llega: hay que comprobar que no vuelven datos.
        offline = tools["sandbox.run_python"](
            "import urllib.request\n"
            "try:\n    urllib.request.urlopen('https://pypi.org', timeout=8)\n    print('online')\n"
            "except Exception:\n    print('offline')"
        )
        assert offline["stdout"].strip() == "offline"
        kernel = tools["sandbox.exec"]("uname -r")["stdout"].strip()
        assert kernel != os.uname().release, "una microVM tiene kernel propio"
    finally:
        sandbox.close()
