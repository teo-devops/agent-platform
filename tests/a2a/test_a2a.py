"""A2A: dónde vive un sub-agente es cosa del despliegue, no del manifiesto.

Nada de esto llama al modelo. El servidor se prueba con un runtime de mentira;
el cliente, contra ese servidor o leyendo respuestas A2A escritas a mano.
"""

from __future__ import annotations

import io
import os
from pathlib import Path

import pytest
from agent_core.config import ConfigStore
from agent_core.errors import ConfigError
from agent_core.result import BuildResult

ROOT = Path(__file__).resolve().parents[2]
ENDPOINTS = "python-developer=http://localhost:9101/,code-reviewer=http://localhost:9102/"


# -- configuración -------------------------------------------------------------


def test_local_runs_every_agent_in_process():
    assert ConfigStore(ROOT, environment="local").remote_agents == {}


def test_the_local_a2a_environment_places_the_specialists_elsewhere():
    remote = ConfigStore(ROOT, environment="local-a2a").remote_agents
    assert remote == {
        "python-developer": "http://127.0.0.1:9101/",
        "code-reviewer": "http://127.0.0.1:9102/",
        "data-provider": "http://127.0.0.1:9103/",
        # El resto del catálogo, para Langflow. No son sub-agentes de nadie: sólo
        # dicen dónde llamarlos, no cambian cómo se construye ningún coordinador.
        "tech-researcher": "http://127.0.0.1:9104/",
        "tech-writer": "http://127.0.0.1:9105/",
        "tech-explainer": "http://127.0.0.1:9106/",
        "release-manager": "http://127.0.0.1:9107/",
        "software-manager": "http://127.0.0.1:9108/",
    }


def test_the_variable_wins_over_the_environment_file(monkeypatch):
    monkeypatch.setenv("AGENT_A2A_ENDPOINTS", "python-developer=http://elsewhere:1/")
    remote = ConfigStore(ROOT, environment="local-a2a").remote_agents
    assert remote["python-developer"] == "http://elsewhere:1/"
    assert remote["code-reviewer"] == "http://127.0.0.1:9102/"


def test_a_malformed_variable_is_an_error(monkeypatch):
    monkeypatch.setenv("AGENT_A2A_ENDPOINTS", "python-developer")
    with pytest.raises(ConfigError, match="agent=url"):
        ConfigStore(ROOT, environment="local").remote_agents


# -- construcción --------------------------------------------------------------


def _factory(runtime: str, monkeypatch):
    from agent_runtime import load_platform

    monkeypatch.setenv("AGENT_A2A_ENDPOINTS", ENDPOINTS)
    os.environ.setdefault("GEMINI_API_KEY", "test-key-not-used")
    return load_platform(root=ROOT, environment="local", runtime=runtime, load_env_file=False)


def test_the_factory_hands_out_an_a2a_delegate(monkeypatch):
    from agent_a2a import A2ADelegate

    factory = _factory("adk", monkeypatch)
    remote = factory.remote("python-developer")
    assert isinstance(remote, A2ADelegate) and remote.url == "http://localhost:9101/"
    assert factory.remote("software-manager") is None


@pytest.mark.parametrize("runtime", ["adk", "langgraph", "langchain"])
def test_a_remote_sub_agent_is_a_tool_with_the_same_name(runtime, monkeypatch):
    """El coordinador no distingue un hijo en proceso de uno remoto: mismo nombre de tool."""
    factory = _factory(runtime, monkeypatch)
    names = _tool_names(factory.build("software-manager"))
    assert {"python_developer", "code_reviewer"} <= names


@pytest.mark.parametrize("runtime", ["adk", "langgraph", "langchain"])
def test_a_remote_sub_agent_is_not_built_in_process(runtime, monkeypatch):
    factory = _factory(runtime, monkeypatch)
    built = []
    original = factory.build

    def spy(name):
        built.append(name)
        return original(name)

    factory.build = spy
    factory.build("software-manager")
    assert built == ["software-manager"]


def _tool_names(result: BuildResult) -> set[str]:
    agent = result.agent
    tools = getattr(agent, "tools", None)
    if tools is not None:  # ADK
        return {getattr(t, "name", None) or t.__name__ for t in tools}
    # LangGraph / LangChain: the tools node of the compiled graph
    node = agent.nodes["tools"].bound
    return set(node.tools_by_name)


# -- servidor y cliente --------------------------------------------------------


class _EchoRuntime:
    name = "fake"

    def app(self, result):
        return result

    async def stream(self, app, message):
        yield "eco: "
        yield message


class _Factory:
    """Lo mínimo que `build_app` le pide a una fábrica."""

    def __init__(self, store):
        self.store = store

    def build(self, name):
        return BuildResult(agent=None, manifest=self.store.load(name))

    def runtime_name(self, manifest):
        return "fake"

    def runtime(self, name):
        return _EchoRuntime()


@pytest.fixture
def served(store):
    from agent_a2a.server import build_app
    from starlette.testclient import TestClient

    app = build_app(_Factory(store), "python-developer", url="http://test/", log=io.StringIO())
    with TestClient(app) as client:
        yield client


def test_the_card_describes_the_manifest(served):
    card = served.get("/.well-known/agent-card.json").json()
    assert card["name"] == "python-developer"
    assert card["url"] == "http://test/"
    assert "framework:fake" in card["skills"][0]["tags"]


def test_message_send_runs_the_agent_and_answers(served):
    from agent_a2a.client import _payload, answer_text

    body = served.post("/", json=_payload("una mediana")).json()
    assert answer_text(body["result"]) == "eco: una mediana"


@pytest.mark.parametrize(
    ("result", "text"),
    [
        ({"kind": "message", "parts": [{"kind": "text", "text": "hola"}]}, "hola"),
        (  # kagent: una tarea con artefactos
            {"kind": "task", "status": {"state": "completed"},
             "artifacts": [{"parts": [{"kind": "text", "text": "código"}]}]},
            "código",
        ),
        (
            {"kind": "task", "status": {"state": "completed",
                                        "message": {"parts": [{"kind": "text", "text": "en el estado"}]}}},
            "en el estado",
        ),
    ],
)
def test_answer_text_reads_messages_and_tasks(result, text):
    from agent_a2a.client import answer_text

    assert answer_text(result) == text


def test_an_unreachable_agent_is_a_platform_error():
    from agent_a2a import A2ADelegate
    from agent_core.errors import PlatformError

    with pytest.raises(PlatformError, match="could not reach"):
        A2ADelegate(name="nadie", url="http://127.0.0.1:9/", timeout=1)("hola")


# -- narración -----------------------------------------------------------------


def test_the_narrator_tells_delegations_hops_and_tools():
    from agent_core.telemetry.narration import Narrator
    from opentelemetry.sdk.trace import TracerProvider

    out = io.StringIO()
    provider = TracerProvider()
    provider.add_span_processor(Narrator(
        agents={"software_manager": "software-manager", "python_developer": "python-developer"},
        delegates={"python_developer": "python-developer"},
        out=out,
    ))
    tracer = provider.get_tracer("test")

    with tracer.start_as_current_span("invoke_agent software_manager"):
        with tracer.start_as_current_span("execute_tool python_developer") as tool:
            with tracer.start_as_current_span("a2a.send", attributes={"a2a.url": "http://x/", "a2a.agent": "python-developer"}):
                pass
            tool.set_attribute("gcp.vertex.agent.tool_response", '{"result": "def f(): ..."}')
        with tracer.start_as_current_span("execute_tool check_syntax") as check:
            check.set_attribute("gen_ai.tool.name", "check_syntax")
            check.set_attribute("gcp.vertex.agent.tool_response", '{"valid": true}')

    lines = out.getvalue().splitlines()
    assert lines[0] == "▶ software-manager"
    assert lines[1] == "  → delega en python-developer"
    assert lines[2] == "    ⇄ A2A message/send → http://x/"
    assert lines[4].startswith("  ← python-developer responde") and lines[4].endswith("def f(): ...")
    assert lines[5].startswith("  · check_syntax(") and lines[5].endswith('{"valid": true}')


def test_participants_names_agents_and_delegates(factory):
    agents, delegates = factory.participants("software-manager")
    assert agents["software_manager"] == "software-manager"
    assert delegates == {"python_developer": "python-developer", "code_reviewer": "code-reviewer"}


# -- resiliencia ---------------------------------------------------------------


def _answering(*responses):
    """Un transporte httpx que responde en orden: un status, o una excepción."""
    import httpx

    sent = []
    queue = list(responses)

    def handler(request):
        sent.append(request)
        step = queue.pop(0)
        if isinstance(step, Exception):
            raise step
        if step == 200:
            body = {"jsonrpc": "2.0", "id": "1",
                    "result": {"kind": "message", "parts": [{"kind": "text", "text": "hecho"}]}}
            return httpx.Response(200, json=body)
        return httpx.Response(step, text="gateway")

    return httpx.MockTransport(handler), sent


@pytest.fixture
def transport(monkeypatch):
    """Instala un transporte falso en los clientes httpx que abre el delegado."""
    import functools

    import httpx

    def install(*responses):
        mock, sent = _answering(*responses)
        monkeypatch.setattr(httpx, "Client", functools.partial(httpx.Client, transport=mock))
        return sent

    return install


def _delegate(url, **kwargs):
    from agent_a2a import A2ADelegate
    from agent_a2a.client import _BREAKERS

    _BREAKERS.pop(url, None)
    return A2ADelegate(name="dev", url=url, backoff=0, **kwargs)


def test_a_refused_connection_is_retried(transport):
    import httpx

    sent = transport(httpx.ConnectError("refused"), 200)
    assert _delegate("http://retry-connect/")("hola") == "hecho"
    assert len(sent) == 2


def test_a_gateway_error_is_retried(transport):
    sent = transport(503, 200)
    assert _delegate("http://retry-503/")("hola") == "hecho"
    assert len(sent) == 2


def test_a_read_timeout_is_not_retried_the_agent_may_be_working(transport):
    import httpx
    from agent_core.errors import PlatformError

    sent = transport(httpx.ReadTimeout("slow"), 200)
    with pytest.raises(PlatformError, match="could not reach"):
        _delegate("http://no-retry-read/")("hola")
    assert len(sent) == 1


def test_the_circuit_opens_after_failures_in_a_row(transport):
    import httpx
    from agent_a2a import CircuitOpenError
    from agent_core.errors import PlatformError

    sent = transport(*[httpx.ConnectError("down")] * 3)
    delegate = _delegate("http://breaker/", retries=0)
    for _ in range(3):
        with pytest.raises(PlatformError, match="could not reach"):
            delegate("hola")
    with pytest.raises(CircuitOpenError, match="3 times in a row"):
        delegate("hola")
    assert len(sent) == 3  # la cuarta ni se intentó


# -- idempotencia --------------------------------------------------------------


def test_a_repeated_message_id_runs_the_agent_once(store):
    """Un reintento con el mismo messageId recibe la misma respuesta sin volver a ejecutar."""
    from agent_a2a.client import _payload, answer_text
    from agent_a2a.server import build_app
    from starlette.testclient import TestClient

    runs = []

    class _CountingRuntime(_EchoRuntime):
        async def stream(self, app, message):
            runs.append(message)
            yield f"respuesta {len(runs)}"

    factory = _Factory(store)
    factory.runtime = lambda name: _CountingRuntime()
    with TestClient(build_app(factory, "python-developer", url="http://test/", log=io.StringIO())) as client:
        payload = _payload("una mediana")
        first = answer_text(client.post("/", json=payload).json()["result"])
        again = answer_text(client.post("/", json=payload).json()["result"])
        other = answer_text(client.post("/", json=_payload("una mediana")).json()["result"])

    assert first == again == "respuesta 1"
    assert other == "respuesta 2", "otro messageId es otra petición"
    assert len(runs) == 2


@pytest.mark.asyncio
async def test_a_failure_is_not_remembered():
    from agent_a2a.server import Deduplicator

    seen, attempts = Deduplicator(), []

    async def flaky():
        attempts.append(1)
        if len(attempts) == 1:
            raise RuntimeError("503")
        return "bien"

    with pytest.raises(RuntimeError):
        await seen.run("m-1", flaky)
    assert await seen.run("m-1", flaky) == ("bien", False)
