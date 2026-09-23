"""Calling an agent that runs in another process, over A2A.

One JSON-RPC method is enough for delegation: ``message/send``. The answer is
either a ``Message`` or a ``Task``; kagent answers with tasks, a server of this
package with messages, and :func:`answer_text` reads both.

Each call opens an ``a2a.send`` span and injects ``traceparent`` into the
request, so a trace that crosses the wire is still one trace — in MLflow, and in
``agentctl run -v``.
"""

from __future__ import annotations

import os
import uuid
from contextlib import contextmanager
from typing import Any, Iterator

import httpx

from agent_core.errors import PlatformError

#: Delegating to an agent means waiting for a model, maybe several: be patient.
DEFAULT_TIMEOUT = float(os.getenv("AGENT_A2A_TIMEOUT", "300"))
CARD_PATH = "/.well-known/agent-card.json"


class A2AError(PlatformError):
    """The remote agent could not be reached, or answered with an error."""


class A2ADelegate:
    """A sub-agent behind an A2A URL, callable like the in-process one.

    ``delegate(text)`` for synchronous code, ``await delegate.acall(text)`` for
    async code; both return the agent's answer as text.
    """

    def __init__(self, *, name: str, url: str, timeout: float = DEFAULT_TIMEOUT) -> None:
        self.name = name
        self.url = url
        self.timeout = timeout

    def __call__(self, request: str) -> str:
        with _span(self.name, self.url) as span:
            try:
                with httpx.Client(timeout=self.timeout) as client:
                    response = client.post(self.url, json=_payload(request), headers=_headers())
            except httpx.HTTPError as exc:
                raise _unreachable(self.name, self.url, exc) from exc
            return _read(response, self.name, self.url, span)

    async def acall(self, request: str) -> str:
        with _span(self.name, self.url) as span:
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.post(self.url, json=_payload(request), headers=_headers())
            except httpx.HTTPError as exc:
                raise _unreachable(self.name, self.url, exc) from exc
            return _read(response, self.name, self.url, span)

    def __repr__(self) -> str:
        return f"A2ADelegate({self.name!r}, {self.url!r})"


def send(url: str, message: str, *, timeout: float = DEFAULT_TIMEOUT) -> str:
    """Send one message to the agent at ``url`` and return its answer."""
    return A2ADelegate(name=url, url=url, timeout=timeout)(message)


def fetch_card(url: str, *, timeout: float = 10) -> dict[str, Any]:
    """The agent card: how an agent describes itself to other agents."""
    card_url = url.rstrip("/") + CARD_PATH
    try:
        response = httpx.get(card_url, timeout=timeout)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise A2AError(f"no agent card at {card_url}: {exc}") from exc
    return response.json()


def answer_text(result: dict[str, Any]) -> str:
    """The text of an A2A result, whether it came back as a message or a task."""
    if result.get("kind") == "message":
        return _parts_text(result.get("parts", []))

    texts = [_parts_text(artifact.get("parts", [])) for artifact in result.get("artifacts") or []]
    if any(texts):
        return "\n".join(t for t in texts if t)
    status_message = (result.get("status") or {}).get("message") or {}
    if status_message:
        return _parts_text(status_message.get("parts", []))
    # Some servers only leave the answer in the history.
    for message in reversed(result.get("history") or []):
        if message.get("role") == "agent":
            return _parts_text(message.get("parts", []))
    return ""


# -- internals ---------------------------------------------------------------


def _payload(text: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": uuid.uuid4().hex,
        "method": "message/send",
        "params": {
            "message": {
                "kind": "message",
                "role": "user",
                "messageId": uuid.uuid4().hex,
                "parts": [{"kind": "text", "text": text}],
            }
        },
    }


def _headers() -> dict[str, str]:
    headers: dict[str, str] = {}
    try:
        from opentelemetry import propagate

        propagate.inject(headers)
    except ImportError:  # pragma: no cover - tracing is optional
        pass
    return headers


def _read(response: httpx.Response, name: str, url: str, span: Any) -> str:
    try:
        response.raise_for_status()
        body = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise A2AError(f"A2A call to '{name}' at {url} failed: {exc}") from exc

    if "error" in body:
        error = body["error"]
        raise A2AError(f"'{name}' answered with an A2A error {error.get('code')}: {error.get('message')}")

    result = body.get("result") or {}
    state = (result.get("status") or {}).get("state") or result.get("kind", "")
    if span is not None:
        span.set_attribute("a2a.task.state", state)
    if state in {"failed", "rejected", "canceled"}:
        raise A2AError(f"'{name}' ended the task as {state}: {answer_text(result)}")
    return answer_text(result)


def _unreachable(name: str, url: str, exc: Exception) -> A2AError:
    return A2AError(
        f"could not reach '{name}' at {url} ({type(exc).__name__}: {exc}). "
        f"Is it being served? `agentctl a2a serve {name}` or `make a2a-up`."
    )


def _parts_text(parts: list[dict[str, Any]]) -> str:
    return "".join(part.get("text", "") for part in parts if part.get("kind", "text") == "text")


@contextmanager
def _span(name: str, url: str) -> Iterator[Any]:
    try:
        from opentelemetry import trace
    except ImportError:  # pragma: no cover
        yield None
        return
    tracer = trace.get_tracer("agent_platform")
    attributes = {"a2a.agent": name, "a2a.url": url, "a2a.method": "message/send"}
    with tracer.start_as_current_span("a2a.send", attributes=attributes) as span:
        try:
            yield span
        except Exception:
            span.set_attribute("a2a.task.state", "error")
            raise
