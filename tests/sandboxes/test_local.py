"""El backend `local`: cómo traduce el spec a `docker run`, y una prueba real opcional.

La prueba real arranca un contenedor (y puede descargar la imagen), así que sólo
corre con AGENT_SANDBOX_DOCKER_TESTS=1: `make test` sigue sin red y sin Docker.
"""

from __future__ import annotations

import os
import shutil

import pytest
from agent_core.schemas import SandboxSpec

pytest.importorskip("agent_sandbox_local")
from agent_sandbox_local import LocalSandbox, run_args, warnings  # noqa: E402


def _spec(**overrides) -> SandboxSpec:
    return SandboxSpec(backend="local", **overrides)


def test_deny_by_default_means_no_network():
    assert "--network" in (args := run_args(_spec(), container="c"))
    assert args[args.index("--network") + 1] == "none"
    assert warnings(_spec()) == []


def test_the_container_is_locked_down():
    args = run_args(_spec(process={"max_procs": 16}), container="c")
    for flag in ("--read-only", "--cap-drop", "--pids-limit", "--user"):
        assert flag in args
    assert args[args.index("--user") + 1] == "65534:65534"
    assert "/workspace:rw,mode=1777,exec" in args


def test_kubernetes_units_become_docker_units():
    args = run_args(_spec(resources={"cpu": "500m", "memory": "2Gi"}), container="c")
    assert args[args.index("--cpus") + 1] == "0.5"
    assert args[args.index("--memory") + 1] == "2g"


def test_what_docker_cannot_enforce_is_said_out_loud():
    spec = _spec(network={"egress": {"default": "deny", "allow": ["pypi.org"]}}, inference={"route": "platform"})
    assert "--network" not in run_args(spec, container="c")
    found = " ".join(warnings(spec))
    assert "cannot filter by host" in found and "gateway" in found


def test_the_backend_is_installed_under_its_entry_point(registries):
    assert "local" in registries.sandboxes.keys()


@pytest.mark.skipif(
    os.getenv("AGENT_SANDBOX_DOCKER_TESTS") != "1" or shutil.which("docker") is None,
    reason="prueba con Docker real: AGENT_SANDBOX_DOCKER_TESTS=1",
)
def test_a_real_container_runs_code_and_has_no_network():
    from agent_core.sandbox import LazySandbox, sandbox_tools
    from agent_core.schemas import PermissionSpec

    sandbox = LazySandbox(_spec(resources={"command_timeout_seconds": 20}), LocalSandbox(), agent="pytest")
    try:
        tools = sandbox_tools(sandbox, PermissionSpec())
        assert tools["sandbox.run_python"]("print(6 * 7)")["stdout"].strip() == "42"
        offline = tools["sandbox.run_python"](
            "import socket\ntry:\n    socket.create_connection(('1.1.1.1', 53), 3)\n    print('online')\n"
            "except OSError:\n    print('offline')"
        )
        assert offline["stdout"].strip() == "offline"
        assert tools["sandbox.exec"]("touch /usr/x")["exit_code"] != 0
    finally:
        sandbox.close()
