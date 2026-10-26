"""Sandboxes: where the code an agent runs is executed, framework-free.

Until now every tool of the catalogue was pure on purpose — ``code.py`` parses,
it never runs — because there was nowhere safe to run anything. A sandbox is
that somewhere. ``spec.sandbox`` says *what* is isolated (filesystem, egress,
processes, model access); a **backend** says *how*, and is an installed package
advertised under ``agent_platform.sandboxes``:

    local      a Docker container on this machine         platform/sandboxes/local
    openshell  an NVIDIA OpenShell sandbox (planned)      docs/strategy.md
    k8s        a pod with gVisor/Kata (planned)

The tools an agent gets are built here, like the skill tools: one set per
agent, bound to *its* sandbox, so two agents never share a filesystem by
accident. Each runtime only wraps them. Unlike the skill tools they **do** go
through ``permissions.tools`` (``sandbox.exec``...): running a command is
reaching the world, and an environment must be able to forbid it.

The sandbox opens on the first call, not at build time: ``agentctl validate``
and the playgrounds build every agent, and none of them should start a
container to do it.
"""

from __future__ import annotations

import atexit
import posixpath
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Callable, Iterator, Protocol, runtime_checkable

from .errors import BuildError, ConfigError, PermissionDeniedError, PlatformError
from .schemas import PermissionSpec, SandboxSpec
from .telemetry import get_logger, log_event

logger = get_logger("sandbox")

#: Prefix of the references of the sandbox tools.
SANDBOX_TOOL_PREFIX = "sandbox."
#: Characters of stdout/stderr handed back to the model. The rest is cut, saying so.
MAX_OUTPUT = 8000
#: Where ``sandbox_run_python`` leaves the snippet it runs.
SNIPPET = "_snippet.py"


class SandboxError(PlatformError):
    """The sandbox could not be opened, or a command could not be run in it."""


@dataclass(frozen=True)
class ExecResult:
    """What a command left behind."""

    exit_code: int
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False


@runtime_checkable
class SandboxSession(Protocol):
    """One live sandbox. Paths are paths *inside* it."""

    def exec(self, command: str, *, timeout: float) -> ExecResult: ...

    def write_file(self, path: str, content: str) -> None: ...

    def read_file(self, path: str) -> str: ...

    def close(self) -> None: ...


@runtime_checkable
class SandboxBackend(Protocol):
    """Turns a :class:`SandboxSpec` into a live sandbox."""

    name: str

    def open(self, spec: SandboxSpec, *, agent: str) -> SandboxSession: ...


class LazySandbox:
    """The sandbox of one agent, opened on first use and closed at exit."""

    def __init__(self, spec: SandboxSpec, backend: SandboxBackend, *, agent: str) -> None:
        self.spec = spec
        self.backend = backend
        self.agent = agent
        self._session: SandboxSession | None = None
        self._lock = threading.Lock()

    @property
    def session(self) -> SandboxSession:
        with self._lock:
            if self._session is None:
                log_event(logger, "opening sandbox", agent=self.agent, backend=self.backend.name)
                try:
                    self._session = self.backend.open(self.spec, agent=self.agent)
                except PlatformError:
                    raise
                except Exception as exc:  # noqa: BLE001 - whatever the backend raised
                    raise SandboxError(
                        f"backend '{self.backend.name}' could not open a sandbox for "
                        f"'{self.agent}': {type(exc).__name__}: {exc}"
                    ) from exc
                atexit.register(self.close)
            return self._session

    def close(self) -> None:
        with self._lock:
            if self._session is not None:
                try:
                    self._session.close()
                finally:
                    self._session = None


def resolve_backend(spec: SandboxSpec, registry: Any, *, agent: str) -> SandboxBackend:
    """The installed backend ``spec.backend`` names."""
    try:
        backend = registry.get(spec.backend)
    except Exception:
        raise BuildError(
            f"agent '{agent}' asks for sandbox backend '{spec.backend}', which is not installed. "
            f"Available: {', '.join(registry.keys()) or 'none'}. "
            f"For 'local': pip install -e platform/sandboxes/local"
        ) from None
    return backend() if isinstance(backend, type) else backend


def check_sandbox_refs(agent: str, sandbox: SandboxSpec, tool_refs: list[str]) -> None:
    """A ``sandbox.*`` tool listed in ``spec.tools`` is a mistake worth explaining."""
    listed = [ref for ref in tool_refs if ref.startswith(SANDBOX_TOOL_PREFIX)]
    if not listed:
        return
    hint = ("they come with spec.sandbox; drop them from spec.tools" if sandbox.enabled
            else "declare spec.sandbox (e.g. profile: code-exec) to get them")
    raise ConfigError(f"agent '{agent}' lists {listed} in spec.tools: {hint}")


def sandbox_tools(
    sandbox: LazySandbox,
    permissions: PermissionSpec,
) -> dict[str, Callable[..., dict[str, Any]]]:
    """The functions each runtime will wrap, keyed by platform reference.

    Named ``sandbox_exec`` and so on, because the three frameworks take the
    tool name from ``__name__``. Tools the permissions deny are not built, and
    with ``process.allow_exec: false`` only the file tools are.
    """
    spec = sandbox.spec
    timeout = spec.resources.command_timeout_seconds

    def sandbox_exec(command: str) -> dict[str, Any]:
        """Runs a shell command inside your isolated sandbox and returns its output.

        The sandbox is a scratch machine: its working directory is /workspace,
        and network access is limited to what your configuration allows.

        Args:
            command: The shell command to run, e.g. "python -m pytest -q".

        Returns:
            A dict with 'exit_code', 'stdout', 'stderr' and 'timed_out'.
        """
        return _run(sandbox, "exec", lambda s: _result(s.exec(command, timeout=timeout)), command=command)

    def sandbox_run_python(code: str) -> dict[str, Any]:
        """Runs a Python program inside your isolated sandbox and returns its output.

        Args:
            code: The complete Python source to run.

        Returns:
            A dict with 'exit_code', 'stdout', 'stderr' and 'timed_out'.
        """
        path = posixpath.join(_workdir(spec), SNIPPET)

        def run(session: SandboxSession) -> dict[str, Any]:
            session.write_file(path, code)
            return _result(session.exec(f"python3 {path}", timeout=timeout))

        return _run(sandbox, "run_python", run, command=f"python3 {path}")

    def sandbox_write_file(path: str, content: str) -> dict[str, Any]:
        """Writes a text file inside your isolated sandbox, replacing it if it exists.

        Args:
            path: Where to write it. Relative paths are inside /workspace.
            content: The full text of the file.

        Returns:
            A dict with the absolute 'path' written and its size in 'bytes'.
        """
        try:
            target = _inside(spec, path, writable=True)
        except ValueError as exc:
            return {"error": str(exc)}

        def write(session: SandboxSession) -> dict[str, Any]:
            session.write_file(target, content)
            return {"path": target, "bytes": len(content.encode())}

        return _run(sandbox, "write_file", write, path=target)

    def sandbox_read_file(path: str) -> dict[str, Any]:
        """Reads a text file from your isolated sandbox.

        Args:
            path: The file to read. Relative paths are inside /workspace.

        Returns:
            A dict with the 'path' and its 'content'.
        """
        try:
            target = _inside(spec, path, writable=False)
        except ValueError as exc:
            return {"error": str(exc)}
        return _run(sandbox, "read_file",
                    lambda s: {"path": target, "content": _cut(s.read_file(target))}, path=target)

    functions: dict[str, Callable[..., dict[str, Any]]] = {
        "sandbox.write_file": sandbox_write_file,
        "sandbox.read_file": sandbox_read_file,
    }
    if spec.process.allow_exec:
        functions = {"sandbox.exec": sandbox_exec, "sandbox.run_python": sandbox_run_python, **functions}
    return {ref: fn for ref, fn in functions.items() if permissions.tools.permits(ref)}


# -- internals ---------------------------------------------------------------


def _run(sandbox: LazySandbox, operation: str, action: Callable[[SandboxSession], dict[str, Any]],
         **attributes: Any) -> dict[str, Any]:
    """Run ``action`` on the session, turning failures into an answer for the model.

    A tool that raises ends the turn in some frameworks and not in others; one
    that answers ``{"error": ...}`` lets the model read what went wrong and
    adapt, the same way on all three.
    """
    with _span(operation, sandbox, attributes) as span:
        try:
            result = action(sandbox.session)
        except (SandboxError, PermissionDeniedError) as exc:
            log_event(logger, "sandbox operation failed", agent=sandbox.agent, operation=operation, error=str(exc))
            if span is not None:
                span.set_attribute("sandbox.error", str(exc))
            return {"error": str(exc)}
        if span is not None and "exit_code" in result:
            span.set_attribute("sandbox.exit_code", result["exit_code"])
            span.set_attribute("sandbox.timed_out", result["timed_out"])
        return result


def _result(result: ExecResult) -> dict[str, Any]:
    return {
        "exit_code": result.exit_code,
        "stdout": _cut(result.stdout),
        "stderr": _cut(result.stderr),
        "timed_out": result.timed_out,
    }


def _cut(text: str) -> str:
    if len(text) <= MAX_OUTPUT:
        return text
    return text[:MAX_OUTPUT] + f"\n[... {len(text) - MAX_OUTPUT} more characters cut]"


def _workdir(spec: SandboxSpec) -> str:
    return spec.filesystem.write[0] if spec.filesystem.write else "/workspace"


def _inside(spec: SandboxSpec, path: str, *, writable: bool) -> str:
    """Normalise ``path`` and check it is inside the paths the spec grants."""
    absolute = posixpath.normpath(posixpath.join(_workdir(spec), path))
    roots = spec.filesystem.write if writable else [*spec.filesystem.read, *spec.filesystem.write]
    if not any(absolute == root or absolute.startswith(root.rstrip("/") + "/") for root in roots):
        verb = "write" if writable else "read"
        raise ValueError(f"'{path}' is outside what this sandbox may {verb}: {roots}")
    return absolute


@contextmanager
def _span(operation: str, sandbox: LazySandbox, attributes: dict[str, Any]) -> Iterator[Any]:
    try:
        from opentelemetry import trace
    except ImportError:  # pragma: no cover - tracing is optional
        yield None
        return
    tracer = trace.get_tracer("agent_platform")
    attrs = {"sandbox.backend": sandbox.backend.name, "sandbox.agent": sandbox.agent,
             **{f"sandbox.{k}": str(v)[:200] for k, v in attributes.items()}}
    with tracer.start_as_current_span(f"sandbox.{operation}", attributes=attrs) as span:
        yield span
