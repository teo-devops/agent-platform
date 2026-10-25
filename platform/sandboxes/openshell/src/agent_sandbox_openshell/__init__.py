"""Sandbox backend ``openshell``: NVIDIA OpenShell, the policy enforced out of process.

OpenShell runs each sandbox under a declarative policy applied *outside* the
workload: Landlock for the filesystem, seccomp and an unprivileged identity for
processes, and a proxy that allows or denies every outbound connection. Network
access is denied unless a rule allows it, and provider credentials never enter
the sandbox: the workload sees placeholders the proxy resolves.

This backend translates ``spec.sandbox`` into that policy (:func:`render_policy`)
and drives the ``openshell`` CLI (v0.1.x) against a running gateway:

    openshell sandbox create --name N --from IMAGE --policy F --detach -- sleep TTL
    openshell sandbox exec -n N --no-tty -- sh -c '...'
    openshell sandbox delete N

How each part of the spec is honoured:

    filesystem.read/write   filesystem_policy (Landlock, hard_requirement)
    network.egress          deny by default; one network rule per allowed host
    process                 run as UID/GID 1000; never root
    inference.route         platform -> --provider $AGENT_OPENSHELL_PROVIDER
                            none     -> --no-auto-providers: no credentials at all
                            direct   -> refused: it would put keys in the sandbox
    resources.cpu/memory    --cpu / --memory (same Kubernetes units as the spec)

Verified against a real gateway (OpenShell 0.1.5): the effective policy
(`sandbox get --policy-only`) is exactly what render_policy produces; a path
the Unix permissions allow but the policy does not (`/home/sandbox`) is denied,
so it is Landlock and not file modes doing it; and an outbound connection is
refused at connect(), raw TCP included.
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

import yaml
from agent_core.errors import ConfigError
from agent_core.sandbox import ExecResult, SandboxError
from agent_core.schemas import SandboxSpec
from agent_core.telemetry import get_logger, log_event

from .version import __version__

logger = get_logger("sandbox.openshell")

#: Read-only paths a process needs to run at all: OpenShell's own default policy.
RUNTIME_READ_ONLY = ["/bin", "/usr", "/lib", "/etc", "/proc", "/dev/urandom"]
#: Writable paths every process expects.
RUNTIME_READ_WRITE = ["/tmp", "/dev/null"]
#: Identity the workload runs as. OpenShell rejects root.
RUN_AS = "1000"
#: Executables a network rule applies to. Our spec does not restrict binaries.
NETWORK_BINARIES = ["/usr/bin/*", "/usr/local/bin/*"]
#: Image used when the spec names none (deploy/images/Dockerfile.sandbox).
DEFAULT_IMAGE = "agent-platform/sandbox:0.1.0"
DEFAULT_TTL = 3600
#: Seconds to wait for a new sandbox to be ready.
READY_TIMEOUT = 180
#: Prefix of every sandbox this backend creates.
NAME_PREFIX = "ap-"
#: OpenShell 0.1.5 rejects longer sandbox names ("name exceeds maximum length").
MAX_NAME = 19
#: Provider (credentials) attached when `inference.route: platform`.
PROVIDER_VARIABLE = "AGENT_OPENSHELL_PROVIDER"
#: Exit code of coreutils `timeout` when the command ran out of time.
TIMEOUT_EXIT = 124

__all__ = ["OpenShellSandbox", "OpenShellSession", "__version__", "create_args", "render_policy",
           "sandbox_name", "warnings"]


def render_policy(spec: SandboxSpec) -> dict[str, Any]:
    """The OpenShell policy (``version: 1``) that expresses ``spec``. Pure, so it can be tested.

    Raises:
        ConfigError: for what OpenShell cannot express without weakening the
            sandbox: egress allowed by default, or model calls with the keys inside.
    """
    egress = spec.network.egress
    if egress.default == "allow":
        raise ConfigError(
            "sandbox.network.egress.default 'allow' cannot be expressed in OpenShell, which denies "
            "egress unless a rule allows it. List the hosts in egress.allow instead."
        )
    if spec.inference.route == "direct":
        raise ConfigError(
            "sandbox.inference.route 'direct' would put provider credentials inside the sandbox, which "
            "is what OpenShell exists to avoid. Use 'platform' (an OpenShell provider) or 'none'."
        )

    read_write = _unique([*spec.filesystem.write, *RUNTIME_READ_WRITE])
    read_only = _unique([p for p in [*spec.filesystem.read, *RUNTIME_READ_ONLY] if p not in read_write])
    for path in [*read_only, *read_write]:
        if not path.startswith("/") or ".." in path.split("/"):
            raise ConfigError(f"sandbox path '{path}' must be absolute and must not contain '..'")
    if "/" in read_write:
        raise ConfigError("sandbox.filesystem.write cannot contain '/': OpenShell never makes the root writable")

    policy: dict[str, Any] = {
        "version": 1,
        "filesystem_policy": {"include_workdir": False, "read_only": read_only, "read_write": read_write},
        # Without Landlock the sandbox would run with no filesystem rules: refuse to start instead.
        "landlock": {"compatibility": "hard_requirement"},
        "process": {"run_as_user": RUN_AS, "run_as_group": RUN_AS},
    }
    rules = {}
    for host in egress.allow:
        name, port = _host_port(host)
        rules[_rule_key(name)] = {
            "name": f"egress {host}",
            "endpoints": [{"host": name, "port": port}],
            "binaries": [{"path": path} for path in NETWORK_BINARIES],
        }
    if rules:
        policy["network_policies"] = rules
    return policy


def warnings(spec: SandboxSpec) -> list[str]:
    """What of ``spec`` this backend cannot enforce, said out loud."""
    found = []
    if spec.network.egress.allow:
        found.append(f"network rules for {spec.network.egress.allow} apply to any binary under "
                     f"{NETWORK_BINARIES}: the spec does not restrict which executables connect")
    if spec.process.max_procs:
        found.append("process.max_procs has no OpenShell policy field")
    if spec.inference.route == "platform" and not os.getenv(PROVIDER_VARIABLE):
        found.append(f"inference.route 'platform' without {PROVIDER_VARIABLE}: no provider is attached, "
                     f"so the sandbox cannot reach any model")
    return found


def sandbox_name(agent: str) -> str:
    """``ap-<agent>-<6 hex>``, with the agent cut so the whole fits in :data:`MAX_NAME`."""
    suffix = uuid.uuid4().hex[:6]
    room = MAX_NAME - len(NAME_PREFIX) - len(suffix) - 1
    slug = "".join(c if c.isalnum() else "-" for c in agent.lower())[:room].strip("-") or "agent"
    return f"{NAME_PREFIX}{slug}-{suffix}"


def create_args(spec: SandboxSpec, *, name: str, policy_file: str) -> list[str]:
    """The ``openshell sandbox create`` arguments. Pure, so it can be tested."""
    args = ["sandbox", "create", "--name", name, "--from", spec.image or DEFAULT_IMAGE,
            "--policy", policy_file, "--detach"]
    if spec.resources.cpu:
        args += ["--cpu", spec.resources.cpu]
    if spec.resources.memory:
        args += ["--memory", spec.resources.memory]
    provider = os.getenv(PROVIDER_VARIABLE)
    if spec.inference.route == "platform" and provider:
        args += ["--provider", provider]
    else:
        # Without this the gateway may attach providers on its own, and the
        # sandbox would get credentials its profile never asked for.
        args.append("--no-auto-providers")
    return [*args, "--", "sleep", str(spec.resources.ttl_seconds or DEFAULT_TTL)]


class OpenShellSandbox:
    """The backend: one OpenShell sandbox per agent sandbox."""

    name = "openshell"

    def __init__(self, cli: str = "openshell") -> None:
        self.cli = cli

    def open(self, spec: SandboxSpec, *, agent: str) -> "OpenShellSession":
        if shutil.which(self.cli) is None:
            raise SandboxError(
                f"the 'openshell' sandbox backend needs the '{self.cli}' CLI on PATH. Install it with "
                f"'curl -LsSf https://raw.githubusercontent.com/NVIDIA/OpenShell/main/install.sh | sh'"
            )
        try:
            policy = render_policy(spec)
        except ConfigError as exc:
            raise SandboxError(f"agent '{agent}': {exc}") from exc
        _run(self.cli, "status", timeout=30, hint="is the gateway running? 'systemctl --user status openshell-gateway'")
        for warning in warnings(spec):
            log_event(logger, "sandbox spec not fully enforceable with openshell", agent=agent, detail=warning)

        sandbox = sandbox_name(agent)
        with tempfile.NamedTemporaryFile("w", suffix=".yaml", prefix="openshell-policy-", delete=False) as handle:
            yaml.safe_dump(policy, handle, sort_keys=False)
        try:
            _run(self.cli, *create_args(spec, name=sandbox, policy_file=handle.name), timeout=READY_TIMEOUT)
        finally:
            Path(handle.name).unlink(missing_ok=True)

        session = OpenShellSession(self.cli, sandbox, workdir=_workdir(spec))
        try:
            session.wait_ready(READY_TIMEOUT)
            session.check_workdir()
        except Exception:
            session.close()
            raise
        log_event(logger, "sandbox started", agent=agent, sandbox=sandbox)
        return session


class OpenShellSession:
    """One running OpenShell sandbox."""

    def __init__(self, cli: str, sandbox: str, *, workdir: str) -> None:
        self.cli = cli
        self.sandbox = sandbox
        self.workdir = workdir

    def wait_ready(self, timeout: float) -> None:
        deadline = time.monotonic() + timeout
        state = ""
        while time.monotonic() < deadline:
            state = _phase(_run(self.cli, "sandbox", "get", self.sandbox, "-o", "json", timeout=30))
            if state in {"ready", "running"}:
                return
            if state in {"error", "failed", "completed"}:
                raise SandboxError(f"sandbox {self.sandbox} ended as '{state}' before it was ready: "
                                   f"'openshell logs {self.sandbox}' says why")
            time.sleep(1)
        raise SandboxError(f"sandbox {self.sandbox} was not ready after {timeout:g}s (last state '{state}')")

    def check_workdir(self) -> None:
        probe = f"test -d {shlex.quote(self.workdir)} && test -w {shlex.quote(self.workdir)}"
        if self._exec(["sh", "-c", probe], timeout=30).returncode:
            raise SandboxError(
                f"{self.workdir} does not exist or is not writable by UID {RUN_AS} in the sandbox image. "
                f"Use an image that provides it (make sandbox-image builds one)."
            )

    def exec(self, command: str, *, timeout: float) -> ExecResult:
        limit = str(max(1, int(timeout + 0.999)))
        script = f"cd {shlex.quote(self.workdir)} && {command}"
        try:
            done = self._exec(["timeout", "-k", "5", limit, "sh", "-c", script], timeout=timeout + 30)
        except subprocess.TimeoutExpired as exc:
            return ExecResult(exit_code=-1, stdout=_text(exc.stdout), stderr=_text(exc.stderr), timed_out=True)
        if done.returncode == TIMEOUT_EXIT:
            return ExecResult(exit_code=-1, stdout=done.stdout, stderr=done.stderr, timed_out=True)
        return ExecResult(exit_code=done.returncode, stdout=done.stdout, stderr=done.stderr)

    def write_file(self, path: str, content: str) -> None:
        import posixpath

        script = f"mkdir -p {shlex.quote(posixpath.dirname(path) or '/')} && cat > {shlex.quote(path)}"
        done = self._exec(["sh", "-c", script], timeout=60, stdin=content)
        if done.returncode:
            raise SandboxError(f"could not write {path}: {done.stderr.strip()}")

    def read_file(self, path: str) -> str:
        done = self._exec(["cat", path], timeout=60)
        if done.returncode:
            raise SandboxError(f"could not read {path}: {done.stderr.strip()}")
        return done.stdout

    def close(self) -> None:
        subprocess.run([self.cli, "sandbox", "delete", self.sandbox], capture_output=True, timeout=120)

    def _exec(self, command: list[str], *, timeout: float, stdin: str = "") -> subprocess.CompletedProcess:
        # --no-tty and stdin from a pipe: the CLI then propagates the command's exit code.
        args = [self.cli, "sandbox", "exec", "-n", self.sandbox, "--no-tty", "--", *command]
        return subprocess.run(args, input=stdin, capture_output=True, text=True, timeout=timeout)


# -- internals ---------------------------------------------------------------


def _phase(raw: str) -> str:
    """The lifecycle state of ``sandbox get -o json``, wherever this CLI version puts it."""
    try:
        data = json.loads(raw)
    except ValueError:
        return raw.strip().lower()
    for keys in (("status", "phase"), ("phase",), ("status", "state"), ("state",), ("status",)):
        value: Any = data
        for key in keys:
            value = value.get(key) if isinstance(value, dict) else None
        if isinstance(value, str):
            return value.lower()
    return ""


def _host_port(entry: str) -> tuple[str, int]:
    host, _, port = entry.partition(":")
    if host.startswith("*") and len(host.split(".")) < 3:
        raise ConfigError(f"egress host '{host}': an OpenShell wildcard needs at least three DNS labels "
                          f"(*.example.com), so '{host}' would match too much")
    return host, int(port) if port else 443


def _rule_key(host: str) -> str:
    key = "egress_" + "".join(c if c.isalnum() else "_" for c in host.lstrip("*."))
    return key[:63]


def _unique(items: list[str]) -> list[str]:
    return list(dict.fromkeys(items))


def _workdir(spec: SandboxSpec) -> str:
    return spec.filesystem.write[0] if spec.filesystem.write else "/tmp"


def _run(cli: str, *args: str, timeout: float, hint: str = "") -> str:
    try:
        done = subprocess.run([cli, *args], capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise SandboxError(f"'openshell {' '.join(args[:2])}' did not finish in {timeout:g}s") from exc
    if done.returncode:
        detail = (done.stderr or done.stdout).strip()
        raise SandboxError(f"'openshell {' '.join(args[:2])}' failed: {detail}" + (f" ({hint})" if hint else ""))
    return done.stdout


def _text(value: Any) -> str:
    if value is None:
        return ""
    return value.decode(errors="replace") if isinstance(value, bytes) else str(value)
