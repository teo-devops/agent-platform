"""El sandbox neutro: esquema, tools ligadas a cada agente y lo que se niega."""

from __future__ import annotations

import pytest
from agent_core.errors import BuildError, ConfigError
from agent_core.sandbox import ExecResult, LazySandbox, check_sandbox_refs, resolve_backend, sandbox_tools
from agent_core.schemas import AllowDeny, PermissionSpec, SandboxSpec
from pydantic import ValidationError


class _Session:
    def __init__(self):
        self.files: dict[str, str] = {}
        self.commands: list[str] = []
        self.closed = False

    def exec(self, command, *, timeout):
        self.commands.append(command)
        return ExecResult(exit_code=0, stdout=f"ran: {command}")

    def write_file(self, path, content):
        self.files[path] = content

    def read_file(self, path):
        return self.files[path]

    def close(self):
        self.closed = True


class _Backend:
    name = "fake"

    def __init__(self):
        self.opened = 0
        self.session = _Session()

    def open(self, spec, *, agent):
        self.opened += 1
        return self.session


def _tools(spec: SandboxSpec | None = None, permissions: PermissionSpec | None = None):
    backend = _Backend()
    sandbox = LazySandbox(spec or SandboxSpec(backend="fake"), backend, agent="probe")
    return sandbox_tools(sandbox, permissions or PermissionSpec()), backend


def test_without_backend_there_is_no_sandbox():
    assert not SandboxSpec().enabled
    assert not SandboxSpec(backend="none").enabled
    assert SandboxSpec(backend="local").enabled


def test_a_writable_path_must_be_readable():
    with pytest.raises(ValidationError, match="not inside any readable path"):
        SandboxSpec(backend="local", filesystem={"read": ["/workspace"], "write": ["/etc"]})


def test_the_sandbox_opens_on_first_use_not_at_build():
    tools, backend = _tools()
    assert backend.opened == 0
    tools["sandbox.exec"]("echo hola")
    tools["sandbox.exec"]("echo otra")
    assert backend.opened == 1


def test_files_round_trip_inside_the_workspace():
    tools, backend = _tools()
    assert tools["sandbox.write_file"]("src/a.py", "x = 1") == {"path": "/workspace/src/a.py", "bytes": 5}
    assert tools["sandbox.read_file"]("/workspace/src/a.py")["content"] == "x = 1"


@pytest.mark.parametrize("path", ["/etc/passwd", "../etc/passwd", "/workspace/../root/.ssh/id_rsa"])
def test_paths_outside_the_spec_are_refused_without_opening_anything(path):
    tools, backend = _tools()
    assert "outside" in tools["sandbox.write_file"](path, "x")["error"]
    assert backend.opened == 0


def test_run_python_writes_the_snippet_and_runs_it():
    tools, backend = _tools()
    result = tools["sandbox.run_python"]("print(1)")
    assert result["exit_code"] == 0
    assert backend.session.files == {"/workspace/_snippet.py": "print(1)"}
    assert backend.session.commands == ["python3 /workspace/_snippet.py"]


def test_without_exec_only_the_file_tools_exist():
    tools, _ = _tools(SandboxSpec(backend="fake", process={"allow_exec": False}))
    assert sorted(tools) == ["sandbox.read_file", "sandbox.write_file"]


def test_sandbox_tools_go_through_permissions():
    tools, _ = _tools(permissions=PermissionSpec(tools=AllowDeny(allow=["*"], deny=["sandbox.exec"])))
    assert "sandbox.exec" not in tools
    assert "sandbox.run_python" in tools


def test_tool_names_are_what_the_frameworks_will_show():
    tools, _ = _tools()
    assert {fn.__name__ for fn in tools.values()} == {
        "sandbox_exec", "sandbox_run_python", "sandbox_write_file", "sandbox_read_file"}


def test_long_output_is_cut_and_says_so():
    from agent_core import sandbox as module

    tools, backend = _tools()
    backend.session.exec = lambda command, *, timeout: ExecResult(exit_code=0, stdout="x" * (module.MAX_OUTPUT + 5))
    assert tools["sandbox.exec"]("yes")["stdout"].endswith("5 more characters cut]")


def test_listing_sandbox_tools_by_hand_is_explained():
    with pytest.raises(ConfigError, match="declare spec.sandbox"):
        check_sandbox_refs("a", SandboxSpec(), ["code.metrics", "sandbox.exec"])
    with pytest.raises(ConfigError, match="drop them from spec.tools"):
        check_sandbox_refs("a", SandboxSpec(backend="local"), ["sandbox.exec"])


def test_an_uninstalled_backend_is_a_build_error(registries):
    with pytest.raises(BuildError, match="'nope', which is not installed"):
        resolve_backend(SandboxSpec(backend="nope"), registries.sandboxes, agent="a")


def test_profiles_resolve_from_configs(store):
    spec = store.load("python-executor").spec.sandbox
    assert spec.backend == "local"
    assert spec.network.egress.default == "deny"
    assert spec.network.egress.allow == []


def test_an_agent_without_sandbox_gets_no_sandbox_tools(factory):
    assert factory.sandbox_tools(factory.store.load("python-developer")) == {}


def test_an_agent_with_sandbox_gets_its_own_tools(factory):
    first = factory.sandbox_tools(factory.store.load("python-executor"))
    second = factory.sandbox_tools(factory.store.load("python-executor"))
    assert set(first) == {"sandbox.exec", "sandbox.run_python", "sandbox.write_file", "sandbox.read_file"}
    assert first["sandbox.exec"] is not second["sandbox.exec"]



def test_the_environment_chooses_who_isolates(root):
    """El perfil dice qué se aísla; el entorno, con quién. El manifiesto no cambia."""
    from agent_core.config import ConfigStore

    assert ConfigStore(root, environment="local").load("python-executor").spec.sandbox.backend == "local"
    assert ConfigStore(root, environment="sandbox-sbx").load("python-executor").spec.sandbox.backend == "sbx"
    openshell = ConfigStore(root, environment="sandbox-openshell").load("python-executor").spec.sandbox
    assert openshell.backend == "openshell"
    assert openshell.network.egress.default == "deny", "el qué no cambia con el quién"


def test_the_variable_wins_and_never_gives_a_sandbox_to_who_has_none(root, monkeypatch):
    from agent_core.config import ConfigStore

    monkeypatch.setenv("AGENT_SANDBOX_BACKEND", "openshell")
    store = ConfigStore(root, environment="sandbox-sbx")
    assert store.load("python-executor").spec.sandbox.backend == "openshell"
    assert not store.load("python-developer").spec.sandbox.enabled
