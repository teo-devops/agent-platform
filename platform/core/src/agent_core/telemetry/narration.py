"""Tell, in the terminal, what the agents are doing while they do it.

``agentctl run -v`` and ``agentctl a2a serve -v`` use this to show who delegates
in whom, which tools each agent calls and what travels over A2A — the work that
the final answer hides.

It reads OpenTelemetry spans, not framework events, for the same reason the
rest of the platform does: spans are the one thing ADK, LangGraph and LangChain
already agree on. ADK emits them natively (``invoke_agent``, ``execute_tool``);
the LangChain family through OpenInference (``openinference.span.kind``); the
A2A transport emits its own (``a2a.send``). A span of a nested call has the
caller's span as parent, so the indentation comes for free — in-process or
across a process boundary.

Needs ``opentelemetry-sdk`` (``agent-core[tracing]``). No OTLP endpoint is
needed: narrating and exporting are independent processors on one provider.
"""

from __future__ import annotations

import json
import sys
import threading
from typing import Any, TextIO

try:
    from opentelemetry.sdk.trace import SpanProcessor as _Processor
except ImportError:  # pragma: no cover - enable_narration reports it
    _Processor = object  # type: ignore[assignment,misc]

#: The span the A2A transport opens around one ``message/send``.
A2A_SPAN = "a2a.send"

_PREVIEW = 110


def enable_narration(
    *,
    agents: dict[str, str],
    delegates: dict[str, str],
    out: TextIO | None = None,
) -> bool:
    """Install a :class:`Narrator` on the global tracer provider.

    Args:
        agents: Python name -> catalogue name of every agent that may appear.
        delegates: Tool name -> catalogue name of every sub-agent exposed as a tool.
        out: Where to write. Standard error by default, so the answer on
            standard output can still be piped.

    Returns whether narration is active (``False`` without the SDK).
    """
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
    except ImportError:
        print("aviso: --verbose necesita opentelemetry-sdk (pip install 'agent-core[tracing]')", file=sys.stderr)
        return False

    from . import tracing

    provider = trace.get_tracer_provider()
    if not isinstance(provider, TracerProvider):
        # No exporter: this provider only exists so there are spans to narrate.
        provider = TracerProvider(resource=Resource.create({"service.name": "agentctl"}))
        trace.set_tracer_provider(provider)
    tracing.ensure_instrumented()
    provider.add_span_processor(Narrator(agents=agents, delegates=delegates, out=out or sys.stderr))
    return True


class Narrator(_Processor):  # type: ignore[misc]
    """A span processor that prints delegations, A2A hops and tool calls."""

    def __init__(self, *, agents: dict[str, str], delegates: dict[str, str], out: TextIO) -> None:
        self.agents = agents
        self.delegates = delegates
        self.out = out
        self._color = getattr(out, "isatty", lambda: False)()
        self._lock = threading.Lock()
        #: span id -> (indent of its children, nearest narrated kind and label
        #: at or above it, its own kind and label). Children inherit the first three.
        self._spans: dict[int, tuple[int, str | None, str | None, str | None, str]] = {}

    # -- SpanProcessor ------------------------------------------------------

    def on_start(self, span: Any, parent_context: Any = None) -> None:
        inherited = self._spans.get(span.parent.span_id) if span.parent else None
        level, near_kind, near_label, _, _ = inherited or (0, None, None, None, "")
        kind, label, key = self._classify(span, near_kind, near_label)
        if kind == "agent" and near_kind == "agent" and near_label == label:
            kind = None  # the platform's root span and the framework's name the same agent

        if kind == "agent":
            step = key not in (label, label.replace("-", "_"))
            self._say(level, "▶", f"{key} · {label}" if step else label, "bold")
        elif kind == "delegate":
            request = _preview(_attr(span, "gcp.vertex.agent.tool_call_args", "input.value"))
            self._say(level, "→", f"delega en {label}" + (f": {request}" if request else ""), "cyan")
        elif kind == "a2a":
            self._say(level, "⇄", f"A2A message/send → {_attr(span, 'a2a.url')}", "magenta")

        if kind in {"agent", "delegate", "a2a"}:
            self._spans[span.context.span_id] = (level + 1, kind, label, kind, label)
        else:
            self._spans[span.context.span_id] = (level, near_kind, near_label, kind, label)

    def on_end(self, span: Any) -> None:
        level, _, _, kind, label = self._spans.pop(span.context.span_id, (0, None, None, None, ""))
        seconds = _seconds(span)

        if kind == "delegate":
            answer = _preview(_result(_attr(span, "gcp.vertex.agent.tool_response", "output.value")))
            self._say(level - 1, "←", f"{label} responde ({seconds}): {answer}", "cyan")
        elif kind == "a2a":
            state = _attr(span, "a2a.task.state") or "ok"
            self._say(level - 1, "⇄", f"A2A {state} ({seconds})", "magenta")
        elif kind is None and self._is_tool(span):
            args = _preview(_attr(span, "gcp.vertex.agent.tool_call_args", "input.value"), 50)
            result = _preview(_result(_attr(span, "gcp.vertex.agent.tool_response", "output.value")), 60)
            self._say(level, "·", f"{self._tool_name(span)}({args}) = {result}", "dim")

    def shutdown(self) -> None:  # pragma: no cover - nothing to release
        pass

    def force_flush(self, timeout_millis: int = 30000) -> bool:  # pragma: no cover
        return True

    # -- classification -----------------------------------------------------

    def _classify(self, span: Any, near_kind: str | None, near_label: str | None) -> tuple[str | None, str, str]:
        """What a span is when it starts: ``agent``, ``delegate``, ``a2a`` or nothing.

        Returns ``(kind, label, key)``: the catalogue name it stands for and the
        name the framework used (a workflow step is named after the step).
        By name only: OpenInference writes its attributes (the span kind, the
        tool name) when the span *ends*. Ordinary tool calls are recognised in
        :meth:`on_end`.
        """
        name = span.name or ""
        if name == A2A_SPAN:
            return "a2a", _attr(span, "a2a.agent"), ""
        for prefix in ("invoke_agent ", "invoke_workflow "):  # ADK
            if name.startswith(prefix) and name[len(prefix):] in self.agents:
                key = name[len(prefix):]
                return "agent", self.agents[key], key
        tool = name.split(" ", 1)[1] if name.startswith("execute_tool ") else name
        if tool in self.delegates and near_kind != "delegate":
            return "delegate", self.delegates[tool], tool
        # OpenInference names a graph (or a workflow step) after its agent. The
        # graph a coordinator runs when it delegates shares its name with the
        # tool span above it; any other span with the name of the agent it is
        # already inside is that agent's own plumbing.
        if name in self.agents and (near_kind == "delegate" or near_label != self.agents[name]):
            return "agent", self.agents[name], name
        return None, "", ""

    def _is_tool(self, span: Any) -> bool:
        name = span.name or ""
        if name.startswith("execute_tool "):
            return not self._tool_name(span).startswith("(")  # ADK's "(merged tools)" bookkeeping
        return _attr(span, "openinference.span.kind") == "TOOL"

    def _tool_name(self, span: Any) -> str:
        name = span.name or ""
        explicit = _attr(span, "gen_ai.tool.name", "tool.name")
        if explicit:
            return explicit
        return name.split(" ", 1)[1] if name.startswith("execute_tool ") else name

    # -- output -------------------------------------------------------------

    def _say(self, level: int, mark: str, text: str, style: str) -> None:
        line = f"{'  ' * max(level, 0)}{mark} {text}"
        if self._color:
            code = {"bold": "1", "cyan": "36", "magenta": "35", "dim": "2"}[style]
            line = f"\033[{code}m{line}\033[0m"
        with self._lock:
            print(line, file=self.out, flush=True)


# -- helpers -----------------------------------------------------------------


def _attr(span: Any, *keys: str) -> str:
    attributes = span.attributes or {}
    for key in keys:
        value = attributes.get(key)
        if value not in (None, "", "N/A", "{}"):
            return str(value)
    return ""


def _result(raw: str) -> str:
    """The useful part of a tool result, whichever framework wrapped it."""
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return raw
    if isinstance(data, dict):
        if isinstance(data.get("data"), dict):  # OpenInference: a serialised ToolMessage
            content = data["data"].get("content", "")
            if isinstance(content, list):
                return "".join(p.get("text", "") for p in content if isinstance(p, dict))
            return str(content)
        if set(data) == {"result"}:  # ADK: {"result": ...}
            return str(data["result"])
    return raw


def _preview(text: str, limit: int = _PREVIEW) -> str:
    flat = " ".join(str(text).split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


def _seconds(span: Any) -> str:
    if span.start_time and span.end_time:
        return f"{(span.end_time - span.start_time) / 1e9:.1f}s"
    return "?s"
