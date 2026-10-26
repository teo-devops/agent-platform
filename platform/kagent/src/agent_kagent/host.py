"""What runs inside a BYO pod: one catalogue agent, served over A2A by kagent's SDK.

kagent's contract for a BYO agent is small: a container that speaks A2A on
port 8080 and reads ``KAGENT_URL``, ``KAGENT_NAME`` and ``KAGENT_NAMESPACE``
(the controller injects them). kagent's own SDK fulfils it; this module only
feeds it the graph the platform builds from the manifest — the same graph
``agentctl run`` and LangGraph Studio use, guardrails and permissions included.

Gemini answers with a list of content blocks — the text plus a thought
signature — once a tool has been called. kagent's converter only publishes an
``AIMessage`` whose content is a ``str``, so the agent's actual answer was
dropped and the task ended with nothing but the tool's output. :class:`TextAnswers`
hands kagent the text of each answer instead; the graph's own state is untouched.

Tracing: kagent's SDK installs the OpenTelemetry provider (OTLP gRPC to the
collector). The platform is loaded with ``tracing=False`` and configured after
that, so it reuses kagent's provider and only adds the ``agent.*`` attributes
and the LangChain instrumentor.
"""

from __future__ import annotations

import os
from typing import Any

from agent_core.errors import ConfigError

#: Frameworks this host can serve. ADK is missing on purpose: kagent-adk 0.10
#: pins google-adk<2, and the platform's ADK runtime is on the 2.x line.
SUPPORTED_RUNTIMES = ("langgraph", "langchain")
#: Port of kagent's BYO contract: the controller routes A2A traffic here.
BYO_PORT = 8080


def agent_card(manifest: Any, *, url: str) -> dict[str, Any]:
    """The A2A agent card: how other agents discover what this one does."""
    return {
        "name": manifest.name,
        "description": manifest.metadata.description or manifest.name,
        "url": url,
        "version": manifest.metadata.version,
        "capabilities": {"streaming": True},
        "defaultInputModes": ["text"],
        "defaultOutputModes": ["text"],
        "skills": [
            {
                "id": manifest.name,
                "name": manifest.name,
                "description": manifest.metadata.description or manifest.name,
                "tags": list(manifest.metadata.tags),
            }
        ],
    }


class TextAnswers:
    """The compiled graph, with each answer's content flattened to its text for kagent.

    kagent's executor only calls ``astream(..., stream_mode="updates")``, so
    that is the one method that changes; everything else is the graph's own.
    """

    def __init__(self, graph: Any) -> None:
        self._graph = graph

    def __getattr__(self, name: str) -> Any:
        return getattr(self._graph, name)

    async def astream(self, *args: Any, **kwargs: Any):
        async for event in self._graph.astream(*args, **kwargs):
            yield _flatten(event)


def _flatten(event: Any) -> Any:
    if not isinstance(event, dict):
        return event
    flat = {}
    for node, data in event.items():
        if isinstance(data, dict) and isinstance(data.get("messages"), list):
            data = {**data, "messages": [_as_text(m) for m in data["messages"]]}
        flat[node] = data
    return flat


def _as_text(message: Any) -> Any:
    from langchain_core.messages import AIMessage

    if isinstance(message, AIMessage) and not isinstance(message.content, str):
        return message.model_copy(update={"content": message.text})
    return message


def build_app(name: str, *, runtime: str, environment: str | None = None) -> Any:
    """The FastAPI app kagent's controller will route A2A traffic to."""
    if runtime not in SUPPORTED_RUNTIMES:
        raise ConfigError(
            f"runtime '{runtime}' cannot be hosted as BYO here; use one of {', '.join(SUPPORTED_RUNTIMES)}"
        )

    from agent_core.telemetry import configure_tracing
    from agent_runtime import load_platform
    from kagent.core import KAgentConfig
    from kagent.langgraph import KAgentApp

    factory = load_platform(environment=environment, runtime=runtime, tracing=False)
    result = factory.build(name)
    if result.manifest.kind != "Agent":
        raise ConfigError(f"'{name}' is a {result.manifest.kind}; the BYO host serves agents")

    config = KAgentConfig()
    url = f"http://{name}.{os.getenv('KAGENT_NAMESPACE', 'kagent')}:{BYO_PORT}"
    app = KAgentApp(
        graph=TextAnswers(factory.runtime(runtime).app(result)),
        agent_card=agent_card(result.manifest, url=url),
        config=config,
        tracing=os.getenv("OTEL_TRACING_ENABLED", "false").lower() == "true",
    ).build()

    configure_tracing(service_name=name)
    return app


def serve(name: str, *, runtime: str, environment: str | None, host: str, port: int) -> None:
    import uvicorn

    uvicorn.run(build_app(name, runtime=runtime, environment=environment), host=host, port=port)
