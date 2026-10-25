"""Sandbox backend ``local``: a locked-down Docker container on this machine.

What it is for: running the code an agent writes during development, on a
laptop, with the same ``spec.sandbox`` that a cluster backend will honour later.
What it is not: a security boundary against a determined attacker. A container
shares the host kernel; OpenShell (Landlock + seccomp, out-of-process policy)
or gVisor/Kata are the backends for that.

How each part of the spec is honoured:

    filesystem.write    a tmpfs per path; the rest of the image is read-only
    filesystem.read     the image is readable; there is nothing else mounted
    network.egress      deny + no hosts -> --network none
                        anything else   -> the default bridge, with a warning:
                                           Docker cannot filter by host name
    process             --pids-limit, --cap-drop ALL, no-new-privileges, nobody
    inference           only 'none'; 'platform'/'direct' need a gateway (warned)
    resources           --cpus, --memory, a timeout per command, ttl as the
                        lifetime of the container

Commands run through ``docker exec``; files travel through stdin and ``cat``,
so nothing on the host is ever written by the sandbox.
"""

from __future__ import annotations

import shlex
import shutil
import subprocess
import uuid
from typing import Any

from agent_core.sandbox import ExecResult, SandboxError
from agent_core.schemas import SandboxSpec
from agent_core.telemetry import get_logger, log_event

from .version import __version__

logger = get_logger("sandbox.local")

#: Image used when the spec names none.
DEFAULT_IMAGE = "python:3.12-slim"
#: Lifetime of the container when the spec sets no ttl.
DEFAULT_TTL = 3600
#: Unprivileged uid:gid the commands run as.
USER = "65534:65534"

__all__ = ["LocalSandbox", "LocalSession", "__version__", "run_args"]


class LocalSandbox:
    """The backend: one container per agent sandbox."""

    name = "local"

    def __init__(self, docker: str = "docker") -> None:
        self.docker = docker

    def open(self, spec: SandboxSpec, *, agent: str) -> "LocalSession":
        if shutil.which(self.docker) is None:
            raise SandboxError(
                f"the 'local' sandbox backend needs the '{self.docker}' CLI on PATH, and it is not there"
            )
        for warning in warnings(spec):
            log_event(logger, "sandbox spec not fully enforceable locally", agent=agent, detail=warning)

        container = f"agent-sandbox-{agent}-{uuid.uuid4().hex[:8]}"
        _docker(self.docker, *run_args(spec, container=container), timeout=120)
        log_event(logger, "sandbox started", agent=agent, container=container,
                  image=spec.image or DEFAULT_IMAGE)
        return LocalSession(self.docker, container, workdir=_workdir(spec))


class LocalSession:
    """One running container."""

    def __init__(self, docker: str, container: str, *, workdir: str) -> None:
        self.docker = docker
        self.container = container
        self.workdir = workdir

    def exec(self, command: str, *, timeout: float) -> ExecResult:
        args = [self.docker, "exec", "-w", self.workdir, self.container, "sh", "-c", command]
        try:
            done = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            # The process inside keeps running; kill everything but PID 1.
            subprocess.run([self.docker, "exec", self.container, "sh", "-c", "kill -9 -1"],
                           capture_output=True, timeout=10)
            return ExecResult(exit_code=-1, stdout=_text(exc.stdout), stderr=_text(exc.stderr), timed_out=True)
        return ExecResult(exit_code=done.returncode, stdout=done.stdout, stderr=done.stderr)

    def write_file(self, path: str, content: str) -> None:
        script = f"mkdir -p {shlex.quote(_dirname(path))} && cat > {shlex.quote(path)}"
        done = subprocess.run([self.docker, "exec", "-i", self.container, "sh", "-c", script],
                              input=content, capture_output=True, text=True, timeout=30)
        if done.returncode:
            raise SandboxError(f"could not write {path}: {done.stderr.strip()}")

    def read_file(self, path: str) -> str:
        done = subprocess.run([self.docker, "exec", self.container, "cat", path],
                              capture_output=True, text=True, timeout=30)
        if done.returncode:
            raise SandboxError(f"could not read {path}: {done.stderr.strip()}")
        return done.stdout

    def close(self) -> None:
        subprocess.run([self.docker, "rm", "-f", self.container], capture_output=True, timeout=30)


def run_args(spec: SandboxSpec, *, container: str) -> list[str]:
    """The ``docker run`` arguments that express ``spec``. Pure, so it can be tested."""
    args = [
        "run", "-d", "--rm", "--name", container,
        "--read-only", "--tmpfs", "/tmp:rw,mode=1777,size=64m",
        "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
        "--user", USER,
        "--label", "agent-platform.sandbox=local",
    ]
    for path in spec.filesystem.write:
        args += ["--tmpfs", f"{path}:rw,mode=1777,exec"]
    if _no_network(spec):
        args += ["--network", "none"]
    if spec.process.max_procs:
        args += ["--pids-limit", str(spec.process.max_procs)]
    if spec.resources.cpu:
        args += ["--cpus", _cpus(spec.resources.cpu)]
    if spec.resources.memory:
        args += ["--memory", _memory(spec.resources.memory)]
    args += ["-w", _workdir(spec), spec.image or DEFAULT_IMAGE,
             "sleep", str(spec.resources.ttl_seconds or DEFAULT_TTL)]
    return args


def warnings(spec: SandboxSpec) -> list[str]:
    """What of ``spec`` this backend cannot enforce, said out loud."""
    found = []
    egress = spec.network.egress
    if egress.default == "allow":
        found.append("network.egress.default is 'allow': the container has full network access")
    elif egress.allow:
        found.append(f"network.egress.allow {egress.allow}: Docker cannot filter by host, "
                     f"so the container gets full network access. Use the openshell backend to enforce it")
    if spec.inference.route != "none":
        found.append(f"inference.route '{spec.inference.route}' needs a model gateway; "
                     f"the local backend provides none")
    return found


# -- internals ---------------------------------------------------------------


def _no_network(spec: SandboxSpec) -> bool:
    egress = spec.network.egress
    return egress.default == "deny" and not egress.allow


def _workdir(spec: SandboxSpec) -> str:
    return spec.filesystem.write[0] if spec.filesystem.write else "/tmp"


def _dirname(path: str) -> str:
    import posixpath

    return posixpath.dirname(path) or "/"


def _cpus(value: str) -> str:
    """Kubernetes units (``500m``) to Docker's (``0.5``)."""
    return str(int(value[:-1]) / 1000) if value.endswith("m") else value


def _memory(value: str) -> str:
    """Kubernetes units (``512Mi``, ``2Gi``) to Docker's (``512m``, ``2g``)."""
    for suffix, docker in (("Ki", "k"), ("Mi", "m"), ("Gi", "g")):
        if value.endswith(suffix):
            return value[: -len(suffix)] + docker
    return value


def _docker(docker: str, *args: str, timeout: float) -> str:
    try:
        done = subprocess.run([docker, *args], capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise SandboxError(f"'docker {args[0]}' did not finish in {timeout:g}s") from exc
    if done.returncode:
        raise SandboxError(f"'docker {args[0]}' failed: {done.stderr.strip()}")
    return done.stdout


def _text(value: Any) -> str:
    if value is None:
        return ""
    return value.decode(errors="replace") if isinstance(value, bytes) else str(value)
