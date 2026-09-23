"""From raw traces to "which agent, which version, which prompt, how well".

Traces reach MLflow over OTLP from anywhere: ``agentctl run``, a playground,
a kagent pod. The platform stamps ``agent.*`` / ``prompt.*`` attributes on the
spans (see ``agent_core.telemetry.tracing``); :func:`sync` lifts them to trace
tags — searchable, visible as columns — and resolves the prompt hash to a
Prompt Registry version. :func:`summarize` turns tagged traces into numbers.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Any

import mlflow

from .common import client
from .prompts import version_for_hash

#: Span attributes lifted to trace tags, in this order of precedence.
IDENTITY = ("agent.name", "agent.version", "agent.framework", "prompt.hash", "prompt.version")
#: OpenTelemetry GenAI convention for the agent's name (ADK emits it).
GENAI_AGENT = "gen_ai.agent.name"
#: Tag that marks a trace as already processed.
SYNCED = "agent.synced"


def _trace_id(trace: Any) -> str:
    info = trace.info
    return getattr(info, "trace_id", None) or info.request_id


def _tags(trace: Any) -> dict[str, str]:
    return dict(getattr(trace.info, "tags", None) or {})


def identity(trace: Any) -> dict[str, str]:
    """The agent that answered: the topmost span that carries ``agent.name``.

    Topmost, because a trace that crossed pods over A2A contains several agents,
    and the one the user talked to is the one that started it.
    """
    spans = sorted(trace.data.spans, key=lambda s: s.start_time_ns)
    for span in spans:
        attributes = span.attributes or {}
        if attributes.get("agent.name"):
            return {key: str(attributes[key]) for key in IDENTITY if attributes.get(key)}
    # A playground that serves many agents (adk web) cannot stamp one name on
    # the process; the framework's own GenAI attribute says which one ran.
    for span in spans:
        attributes = span.attributes or {}
        if attributes.get(GENAI_AGENT):
            found = {key: str(attributes[key]) for key in IDENTITY if attributes.get(key)}
            found["agent.name"] = str(attributes[GENAI_AGENT]).replace("_", "-")
            return found
    return {}


def sync(experiment_id: str, *, max_results: int = 200) -> int:
    """Tag every not-yet-tagged trace with its agent identity. Returns how many."""
    c = client()
    # Trace search cannot filter on a missing tag, so already-synced traces are
    # skipped here instead.
    traces = mlflow.search_traces(
        locations=[experiment_id], max_results=max_results, return_type="list", flush=True
    )
    tagged = 0
    for trace in traces:
        if _tags(trace).get(SYNCED):
            continue
        found = identity(trace)
        if found.get("prompt.hash") and not found.get("prompt.version"):
            version = version_for_hash(found["agent.name"], found["prompt.hash"])
            if version:
                found["prompt.version"] = version
        trace_id = _trace_id(trace)
        for key, value in found.items():
            c.set_trace_tag(trace_id, key, value)
        c.set_trace_tag(trace_id, SYNCED, "true" if found else "no-identity")
        tagged += 1
    return tagged


@dataclass
class Group:
    """Numbers for one (agent, version, prompt, framework) combination."""

    key: tuple[str, str, str, str]
    latencies_ms: list[float] = field(default_factory=list)
    tokens: list[int] = field(default_factory=list)
    tool_calls: list[int] = field(default_factory=list)
    errors: int = 0

    @property
    def row(self) -> dict[str, Any]:
        agent, version, prompt, framework = self.key
        return {
            "agent": agent,
            "agent_version": version,
            "prompt_version": prompt,
            "framework": framework,
            "traces": len(self.latencies_ms),
            "p50_latency_ms": round(statistics.median(self.latencies_ms), 1),
            "p95_latency_ms": round(_percentile(self.latencies_ms, 95), 1),
            "avg_tokens": round(statistics.fmean(self.tokens), 1) if self.tokens else None,
            "avg_tool_calls": round(statistics.fmean(self.tool_calls), 2),
            "error_rate": round(self.errors / len(self.latencies_ms), 3),
        }


def summarize(experiment_id: str, *, max_results: int = 500) -> list[dict[str, Any]]:
    """Latency, tokens and tool calls per agent version, prompt version and framework."""
    groups: dict[tuple[str, str, str, str], Group] = {}
    traces = mlflow.search_traces(
        locations=[experiment_id], max_results=max_results, return_type="list", flush=True
    )
    for trace in traces:
        tags = _tags(trace)
        found = {k: tags.get(k) for k in IDENTITY} if tags.get(SYNCED) == "true" else identity(trace)
        if not found.get("agent.name"):
            continue
        key = (
            found["agent.name"],
            found.get("agent.version") or "?",
            found.get("prompt.version") or found.get("prompt.hash") or "?",
            found.get("agent.framework") or "?",
        )
        group = groups.setdefault(key, Group(key))
        info = trace.info
        group.latencies_ms.append(float(getattr(info, "execution_duration", None) or info.execution_time_ms or 0))
        usage = getattr(info, "token_usage", None) or {}
        if usage.get("total_tokens"):
            group.tokens.append(int(usage["total_tokens"]))
        group.tool_calls.append(sum(1 for s in trace.data.spans if _is_tool(s)))
        group.errors += 0 if str(getattr(info, "status", "OK")).endswith("OK") else 1
    return [g.row for g in sorted(groups.values(), key=lambda g: g.key)]


def _is_tool(span: Any) -> bool:
    kind = str(getattr(span, "span_type", "") or "").upper()
    return kind == "TOOL" or span.name.startswith(("execute_tool", "tool."))


def _percentile(values: list[float], pct: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(pct / 100 * (len(ordered) - 1))))
    return ordered[index]


def log_summary(rows: list[dict[str, Any]], experiment_id: str) -> str:
    """Record the summary as a run: one metric per group, plus the table."""
    with mlflow.start_run(experiment_id=experiment_id, run_name="trace-metrics") as run:
        mlflow.set_tag("agent.kind", "trace-metrics")
        for row in rows:
            prefix = f"{row['agent']}.{row['framework']}.p{row['prompt_version']}"
            mlflow.log_metrics({
                f"{prefix}.p50_latency_ms": row["p50_latency_ms"],
                f"{prefix}.avg_tool_calls": row["avg_tool_calls"],
                f"{prefix}.traces": row["traces"],
                **({f"{prefix}.avg_tokens": row["avg_tokens"]} if row["avg_tokens"] is not None else {}),
            })
        if rows:
            mlflow.log_table({k: [r[k] for r in rows] for k in rows[0]}, artifact_file="trace_metrics.json")
        return run.info.run_id
