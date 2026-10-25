"""Sandbox backend ``sbx``: Docker Sandboxes, one microVM per agent sandbox.

Docker's own proposal for isolating agents: every sandbox is a microVM with its
own kernel and its own Docker daemon, created by the ``sbx`` CLI. Nothing of the
host is mounted (the sandbox is created without a workspace path), so the agent
works on the VM's filesystem and never on yours.

How each part of the spec is honoured:

    filesystem.write    the paths are created inside the VM; nothing is mounted
    filesystem.read     the VM image is readable; sbx filesystem rules are fixed
    network.egress      deny + no hosts -> a per-sandbox deny rule for "**"
                        an allow list   -> per-sandbox allow rules, ONLY if the
                                           global policy does not already allow
                                           everything (see below)
    process             the VM is the boundary: the user inside has sudo (warned)
    inference           sbx injects proxy-managed placeholders for provider keys;
                        the platform does not route models through it (warned)
    resources           --cpus, --memory; a timeout per command inside the VM

About the network, measured on sbx v0.42: all traffic leaves through sbx's proxy,
which applies the policy. A denied HTTPS request gets a 403; a raw TCP connect is
accepted but no data reaches the destination; DNS still resolves. And sbx's
global ``local-policy`` allows ``**`` by default. Local rules can only *narrow*
what it allows, so "deny everything except pypi.org" cannot be expressed per
sandbox while that global rule exists. This backend refuses such a spec instead
of silently granting more network than declared, and never edits the global
policy: that would change every sandbox on the machine.
"""

from __future__ import annotations

import math
import re
import shlex
import shutil
import subprocess
import uuid
from typing import Any

from agent_core.sandbox import ExecResult, SandboxError
from agent_core.schemas import SandboxSpec
from agent_core.telemetry import get_logger, log_event

from .version import __version__

logger = get_logger("sandbox.sbx")

#: Prefix of every sandbox this backend creates, so they are easy to tell apart in `sbx ls`.
NAME_PREFIX = "ap-"
#: Seconds `sbx create` may take: it boots a VM.
CREATE_TIMEOUT = 300
#: sbx refuses a microVM with less memory than this.
MIN_MEMORY_MIB = 1024
#: Exit code of coreutils `timeout` when the command ran out of time.
TIMEOUT_EXIT = 124
#: The command that would allow an allow list, given to the user, never run by us.
GLOBAL_ALLOW_ALL_FIX = "sbx policy rm network --id default-allow-all"

__all__ = ["SbxSandbox", "SbxSession", "__version__", "create_args", "global_allows_all", "warnings"]


class SbxSandbox:
    """The backend: one Docker Sandboxes microVM per agent sandbox."""

    name = "sbx"

    def __init__(self, sbx: str = "sbx") -> None:
        self.sbx = sbx

    def open(self, spec: SandboxSpec, *, agent: str) -> "SbxSession":
        if shutil.which(self.sbx) is None:
            raise SandboxError(
                f"the 'sbx' sandbox backend needs the '{self.sbx}' CLI (Docker Sandboxes) on PATH. "
                f"See https://docs.docker.com/ai/sandboxes/get-started/"
            )
        allow = spec.network.egress.allow
        if allow and global_allows_all(_run(self.sbx, "policy", "inspect", "local-policy", timeout=60)):
            raise SandboxError(
                f"agent '{agent}': its sandbox allows only {allow}, but sbx's global policy allows every "
                f"host, and a per-sandbox rule can only narrow it. Removing the global rule "
                f"('{GLOBAL_ALLOW_ALL_FIX}') would affect every sandbox on this machine, so this backend "
                f"will not do it for you. Deny all egress instead, or use the openshell backend."
            )
        for warning in warnings(spec):
            log_event(logger, "sandbox spec not fully enforceable with sbx", agent=agent, detail=warning)

        sandbox = f"{NAME_PREFIX}{_slug(agent)}-{uuid.uuid4().hex[:6]}"
        _run(self.sbx, *create_args(spec, name=sandbox), timeout=CREATE_TIMEOUT)
        session = SbxSession(self.sbx, sandbox, workdir=_workdir(spec))
        try:
            if allow:
                _run(self.sbx, "policy", "allow", "network", "--sandbox", sandbox, ",".join(allow), timeout=60)
            session.prepare(spec.filesystem.write)
        except Exception:
            session.close()
            raise
        log_event(logger, "sandbox started", agent=agent, sandbox=sandbox)
        return session


class SbxSession:
    """One running microVM."""

    def __init__(self, sbx: str, sandbox: str, *, workdir: str) -> None:
        self.sbx = sbx
        self.sandbox = sandbox
        self.workdir = workdir

    def prepare(self, paths: list[str]) -> None:
        """Create the writable paths, owned by the VM's user (it has sudo inside)."""
        quoted = " ".join(shlex.quote(p) for p in paths)
        script = f"sudo mkdir -p {quoted} && sudo chown \"$(id -u):$(id -g)\" {quoted}"
        done = self._exec(["sh", "-c", script], timeout=60)
        if done.returncode:
            raise SandboxError(f"could not prepare {paths} in {self.sandbox}: {done.stderr.strip()}")

    def exec(self, command: str, *, timeout: float) -> ExecResult:
        # The deadline is enforced inside the VM: killing the CLI would leave the process running there.
        limit = str(max(1, math.ceil(timeout)))
        args = ["timeout", "-k", "5", limit, "sh", "-c", command]
        try:
            done = self._exec(args, timeout=timeout + 30, workdir=self.workdir)
        except subprocess.TimeoutExpired as exc:
            return ExecResult(exit_code=-1, stdout=_text(exc.stdout), stderr=_text(exc.stderr), timed_out=True)
        if done.returncode == TIMEOUT_EXIT:
            return ExecResult(exit_code=-1, stdout=done.stdout, stderr=done.stderr, timed_out=True)
        return ExecResult(exit_code=done.returncode, stdout=done.stdout, stderr=done.stderr)

    def write_file(self, path: str, content: str) -> None:
        script = f"mkdir -p {shlex.quote(_dirname(path))} && cat > {shlex.quote(path)}"
        done = self._exec(["sh", "-c", script], timeout=60, stdin=content)
        if done.returncode:
            raise SandboxError(f"could not write {path}: {done.stderr.strip()}")

    def read_file(self, path: str) -> str:
        done = self._exec(["cat", path], timeout=60)
        if done.returncode:
            raise SandboxError(f"could not read {path}: {done.stderr.strip()}")
        return done.stdout

    def close(self) -> None:
        subprocess.run([self.sbx, "rm", "-f", self.sandbox], capture_output=True, timeout=120)

    def _exec(self, command: list[str], *, timeout: float, workdir: str | None = None,
              stdin: str = "") -> subprocess.CompletedProcess:
        args = [self.sbx, "exec", "-i"]
        if workdir:
            args += ["-w", workdir]
        return subprocess.run([*args, self.sandbox, *command], input=stdin,
                              capture_output=True, text=True, timeout=timeout)


def create_args(spec: SandboxSpec, *, name: str) -> list[str]:
    """The ``sbx create`` arguments that express ``spec``. Pure, so it can be tested."""
    args = ["create", "shell", "--name", name, "-q"]
    if spec.resources.cpu:
        args += ["--cpus", str(_cpus(spec.resources.cpu))]
    if spec.resources.memory:
        args += ["-m", _memory(spec.resources.memory)]
    if spec.network.egress.default == "deny" and not spec.network.egress.allow:
        args += ["--deny-network", "**"]
    return args


def global_allows_all(policy_text: str) -> bool:
    """Whether ``sbx policy inspect local-policy`` shows an active allow rule for every host."""
    for line in policy_text.splitlines():
        fields = line.split()
        if len(fields) >= 3 and fields[0] == "allow" and fields[1] == "**" and fields[2] == "network":
            return "inactive" not in fields
    return False


def warnings(spec: SandboxSpec) -> list[str]:
    """What of ``spec`` this backend cannot enforce, said out loud."""
    found = ["process: the VM is the boundary; the user inside it has sudo"]
    if spec.network.egress.default == "allow":
        found.append("network.egress.default is 'allow': the sandbox gets whatever sbx's global policy allows")
    if spec.image:
        found.append(f"image '{spec.image}' is ignored: sbx sandboxes use the 'shell' agent template")
    if spec.inference.route != "none":
        found.append(f"inference.route '{spec.inference.route}': sbx manages provider keys through its proxy; "
                     f"the platform does not route models through it")
    if spec.resources.memory and _mebibytes(spec.resources.memory) < MIN_MEMORY_MIB:
        found.append(f"resources.memory {spec.resources.memory} is below sbx's 1 GiB minimum: the VM gets 1 GiB")
    if spec.resources.ttl_seconds:
        found.append("resources.ttl_seconds: local sbx sandboxes have no TTL; the platform removes them on close")
    return found


# -- internals ---------------------------------------------------------------


def _workdir(spec: SandboxSpec) -> str:
    return spec.filesystem.write[0] if spec.filesystem.write else "/tmp"


def _dirname(path: str) -> str:
    import posixpath

    return posixpath.dirname(path) or "/"


def _slug(agent: str) -> str:
    return re.sub(r"[^a-z0-9-]", "-", agent.lower()).strip("-")[:40] or "agent"


def _cpus(value: str) -> int:
    """Kubernetes units (``500m``, ``2``) to whole CPUs, rounding up: sbx takes integers."""
    amount = int(value[:-1]) / 1000 if value.endswith("m") else float(value)
    return max(1, math.ceil(amount))


def _memory(value: str) -> str:
    """Kubernetes units (``512Mi``, ``2Gi``) to sbx's (``2048m``), never below its 1 GiB minimum."""
    return f"{max(MIN_MEMORY_MIB, _mebibytes(value))}m"


def _mebibytes(value: str) -> int:
    for suffix, factor in (("Ki", 1 / 1024), ("Mi", 1), ("Gi", 1024)):
        if value.endswith(suffix):
            return math.ceil(float(value[: -len(suffix)]) * factor)
    return math.ceil(int(value) / 2**20)  # plain bytes


def _run(sbx: str, *args: str, timeout: float) -> str:
    try:
        done = subprocess.run([sbx, *args], capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise SandboxError(f"'sbx {args[0]}' did not finish in {timeout:g}s") from exc
    if done.returncode:
        raise SandboxError(f"'sbx {' '.join(args[:2])}' failed: {(done.stderr or done.stdout).strip()}")
    return done.stdout


def _text(value: Any) -> str:
    if value is None:
        return ""
    return value.decode(errors="replace") if isinstance(value, bytes) else str(value)
