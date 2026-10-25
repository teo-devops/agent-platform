"""``agentctl openshell policy <agente>``: the OpenShell policy an agent would run under.

To review or audit what a sandbox may reach without creating one. Uses the same
:func:`render_policy` the backend uses, so what it prints is what runs.
"""

from __future__ import annotations

import argparse
import sys
from typing import Any

import yaml


def register(sub: Any) -> None:
    openshell = sub.add_parser("openshell", help="NVIDIA OpenShell: the policy a sandboxed agent would get")
    actions = openshell.add_subparsers(dest="openshell_command", required=True)

    policy = actions.add_parser("policy", help="Print the OpenShell policy generated for an agent's sandbox")
    policy.add_argument("agent")
    policy.set_defaults(func=cmd_policy)


def cmd_policy(args: argparse.Namespace) -> int:
    from agent_core.errors import ConfigError
    from agent_runtime import load_platform

    from . import render_policy, warnings

    factory = load_platform(root=args.root, environment=args.env)
    spec = factory.store.load(args.agent).spec
    sandbox = getattr(spec, "sandbox", None)
    if sandbox is None or not sandbox.enabled:
        print(f"error: '{args.agent}' has no sandbox", file=sys.stderr)
        return 2
    try:
        policy = render_policy(sandbox)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"# OpenShell policy for '{args.agent}' (environment '{factory.environment}', "
          f"backend '{sandbox.backend}')")
    for warning in warnings(sandbox):
        print(f"# warning: {warning}")
    print(yaml.safe_dump(policy, sort_keys=False).rstrip())
    return 0
