"""Tracing: nada sin endpoint; con él, los spans dicen qué agente, versión y prompt respondió.

El proveedor de OpenTelemetry es global y sólo se instala una vez por proceso,
así que los casos con tracing activo corren en un subproceso limpio.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

from agent_core.telemetry import tracing

ROOT = Path(__file__).resolve().parents[2]


def test_without_endpoint_tracing_is_a_no_op(monkeypatch, store):
    for name in tracing.ENDPOINT_VARIABLES:
        monkeypatch.delenv(name, raising=False)
    tracing.reset_for_tests()

    assert tracing.configure_tracing() is False
    with tracing.agent_span(store.load("greeting"), "adk") as span:
        assert span is None


def test_agent_off_switch_wins_over_endpoint(monkeypatch):
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://127.0.0.1:9")
    monkeypatch.setenv("AGENT_TRACING", "off")
    assert tracing.tracing_requested() is False


def test_prompt_hash_ignores_surrounding_whitespace():
    assert tracing.prompt_hash("hola\n") == tracing.prompt_hash("  hola")
    assert len(tracing.prompt_hash("hola")) == 12


def test_agent_attributes_identify_version_framework_and_prompt(store):
    manifest = store.load("health-advisor")
    attributes = tracing.agent_attributes(manifest, "langgraph")

    assert attributes["agent.name"] == "health-advisor"
    assert attributes["agent.version"] == manifest.metadata.version
    assert attributes["agent.framework"] == "langgraph"
    assert attributes["prompt.hash"] == tracing.prompt_hash(manifest.spec.prompt.instruction)


_SCRIPT = textwrap.dedent(
    """
    import json
    from opentelemetry import trace
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    # A host (kagent's SDK, say) that already installed its own provider.
    exporter = InMemorySpanExporter()
    provider = TracerProvider(resource=Resource.create())
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace.set_tracer_provider(provider)

    from agent_runtime import load_platform
    from agent_core.telemetry import agent_span

    factory = load_platform(root=ROOT, environment="local", load_env_file=False)
    manifest = factory.store.load("greeting")
    with agent_span(manifest, "adk", "hola"):
        with trace.get_tracer("t").start_as_current_span("child"):
            pass
    with trace.get_tracer("t").start_as_current_span("ui-root"):
        pass

    print(json.dumps({s.name: dict(s.attributes) for s in exporter.get_finished_spans()}))
    """
)


def test_spans_carry_agent_attributes_and_reuse_the_host_provider():
    env = {
        **os.environ,
        "OTEL_EXPORTER_OTLP_ENDPOINT": "http://127.0.0.1:9",
        "OTEL_RESOURCE_ATTRIBUTES": "agent.name=from-resource,deployment.environment=test",
        "AGENT_TRACING": "on",
    }
    code = f"ROOT = {str(ROOT)!r}\n{_SCRIPT}"
    output = subprocess.run(
        [sys.executable, "-c", code], env=env, capture_output=True, text=True, check=True
    ).stdout.strip().splitlines()[-1]
    spans = json.loads(output)

    root = spans["invoke_agent greeting"]
    assert root["agent.name"] == "greeting"  # the explicit attribute wins
    assert root["agent.framework"] == "adk"
    assert root["input.value"] == "hola"
    assert "prompt.hash" in root

    # A trace started by someone else (a UI) gets the identity of the process...
    assert spans["ui-root"]["agent.name"] == "from-resource"
    assert spans["child"]["agent.name"] == "from-resource"
    # ...but only the agent.* / prompt.* attributes, not the whole resource.
    assert "deployment.environment" not in spans["ui-root"]
