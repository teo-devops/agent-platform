"""``agentctl``: inspect, validate and run the agents defined in a repository.

The CLI never imports an agent module. Everything it shows or runs comes from
the configuration tree, which is the point of the platform: what you see with
``agentctl show`` is exactly what the runtime will execute.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Any

from importlib.metadata import entry_points

import yaml
from agent_core.errors import PlatformError
from agent_core.registry import COMMANDS_GROUP, EVAL_SINKS_GROUP
from agent_core.telemetry import agent_span, flush

from .context import load_platform


#: Dónde viven las suites de evaluación.
EVALS_DIR = "evals"


def _factory(args: argparse.Namespace):
    return load_platform(
        root=args.root, environment=args.env, runtime=getattr(args, "runtime", None)
    )


def _dump(data: Any) -> str:
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True, default_flow_style=False).rstrip()


def cmd_list(args: argparse.Namespace) -> int:
    factory = _factory(args)
    store = factory.store
    print(f"root: {store.root}\nenvironment: {store.environment}\n")

    for name in store.list_agents():
        manifest = store.load_agent(name)
        tools = ", ".join(tool.ref for tool in manifest.spec.enabled_tools) or "-"
        domain = store.domain_of(name) or "-"
        print(
            f"  agent     {name:<22} {domain:<12} runtime={manifest.spec.runtime or '?':<11} "
            f"tools={tools}"
        )

    for name in store.list_workflows():
        manifest = store.load_workflow(name)
        steps = " -> ".join(node.name for node in manifest.spec.nodes) or "-"
        print(
            f"  workflow  {name:<22} {manifest.spec.type:<12} "
            f"runtime={manifest.spec.runtime or '?':<11} steps={steps}"
        )
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    factory = _factory(args)
    manifest = factory.store.load(args.name)
    print(_dump(manifest.model_dump(mode="json", exclude_none=True)))
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    factory = _factory(args)
    names = [args.name] if args.name else [*factory.store.list_agents(), *factory.store.list_workflows()]
    failed = 0
    for name in names:
        problems = factory.validate(name)
        if problems:
            failed += 1
            print(f"FAIL  {name}")
            for problem in problems:
                print(f"      {problem}")
        else:
            print(f"OK    {name}")
    print(f"\n{len(names) - failed}/{len(names)} valid in environment '{factory.environment}'")
    return 1 if failed else 0


def cmd_components(args: argparse.Namespace) -> int:
    factory = _factory(args)
    for label, registry in (
        ("runtimes", factory.registries.runtimes),
        ("tools", factory.registries.tools),
        ("plugins", factory.registries.plugins),
        ("builders", factory.registries.builders),
    ):
        print(f"{label}:")
        for ref in registry.keys():
            print(f"  {ref}")
        if not registry.keys():
            print("  <none installed>")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    factory = _factory(args)
    result = factory.build(args.name)
    runtime = factory.runtime(factory.runtime_name(result.manifest))
    app = runtime.app(result)
    if args.verbose:
        from agent_core.telemetry import enable_narration

        agents, delegates = factory.participants(args.name)
        enable_narration(agents=agents, delegates=delegates)
        remote = {n: u for n, u in factory.store.remote_agents.items() if n in agents}
        for name, url in sorted(remote.items()):
            print(f"  {name} → A2A {url}", file=sys.stderr)

    async def _run() -> None:
        print(f"[{args.name} @ {factory.environment} on {runtime.name}] > {args.message}\n", flush=True)
        with agent_span(result.manifest, runtime.name, args.message):
            async for chunk in runtime.stream(app, args.message):
                # With narration on stderr, a chunk left mid-line would glue the
                # next narrated step onto the answer.
                end = "\n" if args.verbose and not chunk.endswith("\n") else ""
                print(chunk, end=end, flush=True)
        print()

    asyncio.run(_run())
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    """Publish the resolved form of manifests for whoever runs them.

    Not a translation: same ``kind``, same ``apiVersion``, same schema. What
    changes is that nothing is left implicit — topology is spelled out and agent
    references are pinned. See :mod:`agent_core.publish`.
    """
    from agent_core.publish import resolve

    factory = _factory(args)
    store = factory.store

    if args.all:
        if not args.output:
            print("error: --all necesita -o/--output", file=sys.stderr)
            return 2
        names = [*store.list_agents(), *store.list_workflows()]
    elif args.name:
        names = [args.name]
    else:
        print("error: indica un nombre, o usa --all", file=sys.stderr)
        return 2

    directory = Path(args.output) if args.output else None
    failed: list[tuple[str, Exception]] = []
    published = 0

    for name in names:
        try:
            resolved = resolve(store.load(name), store)
        except PlatformError as exc:
            if not args.all:
                raise
            failed.append((name, exc))
            continue

        if directory:
            print(f"  {resolved.write(directory)}")
        else:
            print(_dump(resolved.document))
        published += 1

    if args.all:
        print(f"\n{published}/{len(names)} publicado(s)", file=sys.stderr)
    for name, exc in failed:
        print(f"  FALLO  {name}: {exc}", file=sys.stderr)

    return 1 if failed else 0


def cmd_schema(args: argparse.Namespace) -> int:
    """Emit the JSON Schema of a manifest kind, generated from the models.

    Nobody writes this schema by hand, here or anywhere else. Whoever needs to
    validate our manifests — the platform plane, an editor, CI — consumes what
    this command generates, so the contract cannot drift from the code.
    """
    import json

    from agent_core.schemas import AgentManifest, WorkflowManifest

    models = {"Agent": AgentManifest, "Workflow": WorkflowManifest}
    kinds = [args.kind] if args.kind else list(models)

    for kind in kinds:
        schema = models[kind].model_json_schema(by_alias=True, mode="serialization")
        schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        schema["title"] = f"{kind}Manifest"
        schema["description"] = (
            f"Manifiesto '{kind}' de agents.platform/v1. GENERADO desde los modelos "
            f"pydantic de agent-core con 'agentctl schema' — no editar a mano."
        )
        body = json.dumps(schema, indent=2, ensure_ascii=False) + "\n"

        if args.output:
            target = Path(args.output) / f"{kind.lower()}.schema.json"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(body, encoding="utf-8")
            print(f"  {target}")
        else:
            print(body, end="")

    return 0


def cmd_eval(args: argparse.Namespace) -> int:
    """Ejecutar una suite de evaluación y devolver un número comparable.

    Evaluar un agente exige ejecutarlo, y ejecutarlo exige un modelo: no hay
    forma de puntuar una respuesta que no existe. Lo que sí se puede hacer sin
    credenciales es ``--check``, que valida las suites —esquema, criterios que
    existen, objetivos que existen— sin ejecutar nada. Ese es el gate barato que
    corre en cada commit; la evaluación de verdad corre donde hay clave.

    ``--no-judge`` ejecuta el objetivo pero se salta el juez: útil cuando sólo
    interesan las aserciones deterministas, que no fluctúan.
    """
    from agent_core.evals import load_suite, run_suite
    from agent_core.evals.engine import JUDGE_AGENT

    factory = _factory(args)
    root = factory.store.root
    suites_dir = root / EVALS_DIR

    if args.all:
        names = sorted(p.parent.name for p in suites_dir.glob("*/dataset.yaml"))
    elif args.name:
        names = [args.name]
    else:
        print("error: indica una suite, o usa --all", file=sys.stderr)
        return 2

    if not names:
        print(f"error: no hay suites en {EVALS_DIR}/", file=sys.stderr)
        return 2

    if args.check:
        for name in names:
            suite, _ = load_suite(suites_dir / name)
            objetivo = suite.spec.target
            if objetivo not in [*factory.store.list_agents(), *factory.store.list_workflows()]:
                print(f"  FALLO {name}: evalúa '{objetivo}', que no existe", file=sys.stderr)
                return 1
            print(f"  OK    {name}  ({len(suite.spec.cases)} casos sobre '{objetivo}')")
        print(f"\n{len(names)} suite(s) válida(s).")
        return 0

    judge_runner = None if args.no_judge else _judge_runner(factory, JUDGE_AGENT)
    failed = 0

    for name in names:
        suite, criteria = load_suite(suites_dir / name)
        runtime = factory.runtime(factory.runtime_name(factory.store.load(suite.spec.target)))

        target_runner = _target_runner(factory, runtime, suite.spec.target)
        result = asyncio.run(
            run_suite(
                suite,
                criteria,
                run=target_runner,
                judge=judge_runner,
                only_tag=args.tag,
            )
        )
        for case, trace_id in zip(result.cases, target_runner.trace_ids):
            case.trace_id = trace_id
        failed += 0 if _report(result, runtime.name, judged=result.judged) else 1
        _publish(result, args.sink or [], factory=factory, runtime=runtime.name)

    return 1 if failed else 0


def _target_runner(factory: Any, runtime: Any, target: str):
    """Una corrutina que manda un mensaje al objetivo y devuelve su respuesta."""
    result = factory.build(target)
    app = runtime.app(result)
    trace_ids: list[str | None] = []

    async def run(message: str) -> str:
        with agent_span(result.manifest, runtime.name, message) as span:
            trace_ids.append(format(span.get_span_context().trace_id, "032x") if span else None)
            chunks = [chunk async for chunk in runtime.stream(app, message)]
        return "".join(chunks)

    #: One per call, in order: the engine runs the cases one after another.
    run.trace_ids = trace_ids  # type: ignore[attr-defined]
    return run


def _judge_runner(factory: Any, judge: str):
    """El juez es un agente del catálogo, construido con la misma fábrica."""
    from agent_core.errors import PlatformError

    try:
        runtime = factory.runtime(factory.runtime_name(factory.store.load(judge)))
        return _target_runner(factory, runtime, judge)
    except PlatformError as exc:
        print(
            f"aviso: no se pudo construir el juez '{judge}' ({exc}).\n"
            f"       Se evalúan sólo las aserciones deterministas.",
            file=sys.stderr,
        )
        return None


def _publish(result: Any, sinks: list[str], *, factory: Any, runtime: str) -> None:
    """Enviar el resultado a los sinks pedidos con ``--sink`` (p. ej. ``mlflow``).

    Un sink es un paquete que se anuncia por entry point; el motor de evals no
    sabe que existen. Si falla uno, se avisa y la suite no cambia de veredicto.
    """
    if not sinks:
        return
    flush()  # the sink may look the traces up; make sure they left the process
    available = {entry.name: entry for entry in entry_points(group=EVAL_SINKS_GROUP)}
    for name in sinks:
        entry = available.get(name)
        if entry is None:
            print(
                f"aviso: no hay sink '{name}' instalado (disponibles: "
                f"{', '.join(sorted(available)) or 'ninguno'})",
                file=sys.stderr,
            )
            continue
        try:
            destino = entry.load()(result, {"factory": factory, "runtime": runtime})
            if destino:
                print(f"  -> {name}: {destino}")
        except Exception as exc:  # noqa: BLE001 - publishing must not change the verdict
            print(f"aviso: el sink '{name}' falló: {exc}", file=sys.stderr)


def _report(result: Any, runtime: str, *, judged: bool) -> bool:
    """Imprimir el resultado. Devuelve si la suite pasa el umbral."""
    suite = result.suite
    print(f"\n{suite.name}  ({suite.spec.target} @ {runtime})")

    for case in result.cases:
        if case.passed:
            print(f"  OK    {case.case.id}")
            continue
        print(f"  FALLO {case.case.id}")
        if case.error:
            print(f"        {case.error}")
        for failure in case.failures:
            print(f"        {failure}")

    total = len(result.cases)
    passed = sum(1 for case in result.cases if case.passed)
    ok = result.meets_threshold

    nota = "" if judged else "  (sólo aserciones)"
    print(
        f"  {suite.spec.metric}: {result.score:.2f}  "
        f"umbral {suite.spec.threshold:.2f}  {passed}/{total}{nota}  "
        f"-> {'OK' if ok else 'POR DEBAJO'}"
    )
    return ok


def cmd_ui(args: argparse.Namespace) -> int:
    """Open the development UI of whichever framework runs these manifests."""
    from .ui import launch

    factory = _factory(args)
    runtime = args.runtime or factory.runtime_name(
        factory.store.load(args.agent) if args.agent else None
    )
    return launch(factory, runtime, agent=args.agent, port=args.port)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agentctl", description="Declarative agent platform control CLI")
    parser.add_argument("--root", help="Platform root (default: discovered from the current directory)")
    parser.add_argument("--env", help="Environment overlay to apply (default: $AGENT_ENV or 'local')")
    parser.add_argument(
        "--runtime",
        help="Force a framework for every manifest (adk, langgraph, langchain). "
             "Default: what each manifest declares.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="List the agents and workflows defined in this repository").set_defaults(func=cmd_list)

    show = sub.add_parser("show", help="Print the fully resolved configuration of one agent or workflow")
    show.add_argument("name")
    show.set_defaults(func=cmd_show)

    validate = sub.add_parser("validate", help="Build every manifest without running it")
    validate.add_argument("name", nargs="?")
    validate.set_defaults(func=cmd_validate)

    sub.add_parser("components", help="List the installed tools, plugins and builders").set_defaults(
        func=cmd_components
    )

    run = sub.add_parser("run", help="Send one message to an agent or workflow")
    run.add_argument("name")
    run.add_argument("-m", "--message", required=True, help="The user message to send")
    run.add_argument(
        "-v", "--verbose", action="store_true",
        help="Narrate on stderr who delegates in whom, the tool calls and the A2A hops",
    )
    run.set_defaults(func=cmd_run)

    export = sub.add_parser(
        "export",
        help="Publish the resolved form of manifests (topology explicit, versions pinned)",
    )
    export.add_argument("name", nargs="?")
    export.add_argument("--all", action="store_true", help="Publish every agent and workflow")
    export.add_argument("-o", "--output", help="Directory to write the manifests into")
    export.set_defaults(func=cmd_export)

    evaluate = sub.add_parser(
        "eval",
        help="Run an evaluation suite and report the metric against its threshold",
    )
    evaluate.add_argument("name", nargs="?")
    evaluate.add_argument("--all", action="store_true", help="Run every suite in evals/")
    evaluate.add_argument(
        "--check",
        action="store_true",
        help="Validate the suites without running anything (no API key needed)",
    )
    evaluate.add_argument(
        "--no-judge",
        action="store_true",
        help="Run the target but skip the LLM judge: deterministic assertions only",
    )
    evaluate.add_argument("--tag", help="Only the cases carrying this tag")
    evaluate.add_argument(
        "--sink",
        action="append",
        help="Publish the results somewhere (repeatable), e.g. --sink mlflow",
    )
    evaluate.set_defaults(func=cmd_eval)

    ui = sub.add_parser(
        "ui",
        help="Open the development playground of the runtime (adk web / langgraph dev)",
    )
    ui.add_argument("agent", nargs="?", help="Agent to open (ADK only; default: greeting)")
    ui.add_argument("--port", type=int, help="Port to serve on")
    ui.set_defaults(func=cmd_ui)

    schema = sub.add_parser(
        "schema",
        help="Emit the JSON Schema of a manifest kind, generated from the models",
    )
    schema.add_argument("--kind", choices=["Agent", "Workflow"], help="Default: both")
    schema.add_argument("-o", "--output", help="Directory to write the schemas into")
    schema.set_defaults(func=cmd_schema)

    # Subcommands contributed by other distributions (deploy, mcp, mlflow...).
    # Installing the package is what makes the command exist.
    for entry in entry_points(group=COMMANDS_GROUP):
        entry.load()(sub)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except PlatformError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
