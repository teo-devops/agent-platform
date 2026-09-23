"""``agentctl mlflow``: prompts, agent versions, traces and metrics in MLflow."""

from __future__ import annotations

import argparse
import sys
from typing import Any

#: Where the agents deployed on kagent are listed (see agent-kagent).
RELEASE_FILE = "deploy/kagent/release.yaml"


def register(sub: Any) -> None:
    mlflow_cmd = sub.add_parser("mlflow", help="MLflow as AgentOps backend (MLFLOW_TRACKING_URI)")
    actions = mlflow_cmd.add_subparsers(dest="mlflow_command", required=True)

    init = actions.add_parser("init", help="Create the experiment and print its id (for OTLP headers)")
    init.set_defaults(func=cmd_init)

    prompts = actions.add_parser("prompts", help="Register agent prompts in the Prompt Registry")
    prompts.add_argument("agents", nargs="*", help=f"Default: the agents of {RELEASE_FILE}, or every agent")
    prompts.set_defaults(func=cmd_prompts)

    models = actions.add_parser("register", help="Record agent versions as LoggedModels")
    models.add_argument("agents", nargs="*", help=f"Default: the agents of {RELEASE_FILE}, or every agent")
    models.set_defaults(func=cmd_register)

    sync = actions.add_parser("sync", help="Tag traces with the agent, version and prompt that produced them")
    sync.set_defaults(func=cmd_sync)

    metrics = actions.add_parser("metrics", help="Latency, tokens and tool calls per agent/prompt/framework")
    metrics.add_argument("--no-log", action="store_true", help="Print only; do not record a run")
    metrics.set_defaults(func=cmd_metrics)


def _factory(args: argparse.Namespace):
    from agent_runtime import load_platform

    return load_platform(root=args.root, environment=args.env, runtime=args.runtime, tracing=False)


def _agents(factory, names: list[str]) -> list[str]:
    """Explicit names, else what the kagent release deploys, else the whole catalogue.

    The release is read as plain YAML on purpose: this package does not depend
    on agent-kagent, it only agrees on where the list of deployed agents lives.
    """
    if names:
        return names
    release = factory.store.root / RELEASE_FILE
    if release.exists():
        import yaml

        spec = (yaml.safe_load(release.read_text(encoding="utf-8")) or {}).get("spec", {})
        deployed = [agent["name"] for agent in spec.get("agents", [])]
        if deployed:
            return deployed
    return factory.store.list_agents()


def cmd_init(args: argparse.Namespace) -> int:
    from .common import EXPERIMENT, ensure_experiment

    experiment_id = ensure_experiment()
    print(experiment_id)
    print(f"experimento '{EXPERIMENT}' = {experiment_id}", file=sys.stderr)
    return 0


def cmd_prompts(args: argparse.Namespace) -> int:
    from .common import PROMPT_VERSIONS, ensure_experiment, read_json, write_json
    from .prompts import push

    ensure_experiment()
    factory = _factory(args)
    state_file = factory.store.root / PROMPT_VERSIONS
    # Without names the whole release is pushed, so the file starts over and
    # nothing stale survives; with names, only those entries change.
    versions = read_json(state_file) if args.agents else {}
    for name in _agents(factory, args.agents):
        manifest = factory.store.load(name)
        if manifest.kind != "Agent" or not manifest.spec.prompt.instruction:
            continue
        version, created = push(manifest)
        versions[name] = version
        print(f"  {name:20} v{version}  {'NUEVA' if created else 'sin cambios'}")
    write_json(state_file, versions)
    print(f"\nVersiones en {PROMPT_VERSIONS} (las lee `agentctl kagent render`).")
    return 0


def cmd_register(args: argparse.Namespace) -> int:
    from .common import ensure_experiment
    from .models import register as register_model

    experiment_id = ensure_experiment()
    factory = _factory(args)
    for name in _agents(factory, args.agents):
        if factory.store.load(name).kind != "Agent":
            continue
        model_id, created = register_model(factory, name, experiment_id=experiment_id)
        version = factory.store.load(name).metadata.version
        print(f"  {name + '@' + version:28} {model_id}  {'NUEVO' if created else 'ya existía'}")
    return 0


def cmd_sync(args: argparse.Namespace) -> int:
    from .common import ensure_experiment
    from .traces import sync

    print(f"{sync(ensure_experiment())} traza(s) etiquetada(s)")
    return 0


def cmd_metrics(args: argparse.Namespace) -> int:
    from .common import ensure_experiment
    from .traces import log_summary, summarize, sync

    experiment_id = ensure_experiment()
    sync(experiment_id)
    rows = summarize(experiment_id)
    if not rows:
        print("No hay trazas con identidad de agente todavía.")
        return 0
    columns = list(rows[0])
    widths = {c: max(len(c), *(len(str(r[c])) for r in rows)) for c in columns}
    print("  ".join(c.ljust(widths[c]) for c in columns))
    for row in rows:
        print("  ".join(str(row[c]).ljust(widths[c]) for c in columns))
    if not args.no_log:
        print(f"\nRegistrado como run {log_summary(rows, experiment_id)}")
    return 0
