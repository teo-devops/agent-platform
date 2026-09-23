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
        "python-developer": "http://localhost:9101/",
        "code-reviewer": "http://localhost:9102/",
        "data-provider": "http://localhost:9103/",
    }


def test_the_variable_wins_over_the_environment_file(monkeypatch):
    monkeypatch.setenv("AGENT_A2A_ENDPOINTS", "python-developer=http://elsewhere:1/")
    remote = ConfigStore(ROOT, environment="local-a2a").remote_agents
    assert remote["python-developer"] == "http://elsewhere:1/"
    assert remote["code-reviewer"] == "http://localhost:9102/"


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
