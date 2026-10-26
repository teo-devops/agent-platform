"""Calling an agent that runs in another process, over A2A.

One JSON-RPC method is enough for delegation: ``message/send``. The answer is
either a ``Message`` or a ``Task``; kagent answers with tasks, a server of this
package with messages, and :func:`answer_text` reads both.

Each call opens an ``a2a.send`` span and injects ``traceparent`` into the
request, so a trace that crosses the wire is still one trace — in MLflow, and in
``agentctl run -v``.

Two things keep a coordinator standing when a sub-agent is not:

- **Retries, only where they are safe.** ``message/send`` is not idempotent: a
  request that reached the agent may already be running. So a call is retried
  only when it never got there — the connection was refused — or a gateway in
  between said so (502/503/504). A read timeout is not retried.
- **A circuit breaker per URL.** After a few failures in a row the delegate
  fails fast for a while instead of making every coordinator wait out the same
  dead agent. The error says so, and the coordinator reports it like any other
  tool error.
"""

from __future__ import annotations

import asyncio
import os
import threading
import time
import uuid
from contextlib import contextmanager
from typing import Any, Iterator

import httpx

from agent_core.errors import PlatformError

#: Delegating to an agent means waiting for a model, maybe several: be patient.
DEFAULT_TIMEOUT = float(os.getenv("AGENT_A2A_TIMEOUT", "300"))
#: Extra attempts for a call that never reached the agent.
DEFAULT_RETRIES = int(os.getenv("AGENT_A2A_RETRIES", "2"))
#: Seconds before the first retry; doubles on each attempt.
RETRY_BACKOFF = float(os.getenv("AGENT_A2A_BACKOFF", "0.5"))
#: Failures in a row that open the circuit of a URL.
BREAKER_THRESHOLD = int(os.getenv("AGENT_A2A_BREAKER_THRESHOLD", "3"))
#: Seconds an open circuit fails fast before letting one call through.
BREAKER_COOLDOWN = float(os.getenv("AGENT_A2A_BREAKER_COOLDOWN", "30"))
CARD_PATH = "/.well-known/agent-card.json"

#: Statuses with which a proxy says the request did not reach the agent.
_RETRYABLE_STATUS = {502, 503, 504}


class A2AError(PlatformError):
    """The remote agent could not be reached, or answered with an error."""


class CircuitOpenError(A2AError):
    """The remote agent failed too often recently; the call was not attempted."""


class CircuitBreaker:
    """Counts failures in a row for one URL and fails fast while they pile up."""

    def __init__(self, *, threshold: int = BREAKER_THRESHOLD, cooldown: float = BREAKER_COOLDOWN) -> None:
        self.threshold = threshold
        self.cooldown = cooldown
        self.failures = 0
        self.opened_at: float | None = None
        self._lock = threading.Lock()

    def check(self, name: str, url: str) -> None:
        with self._lock:
            if self.opened_at is None:
                return
            waited = time.monotonic() - self.opened_at
            if waited < self.cooldown:
                raise CircuitOpenError(
                    f"'{name}' at {url} failed {self.failures} times in a row; not calling it "
                    f"for another {self.cooldown - waited:.0f}s"
                )
            self.opened_at = None  # half-open: let this one through

    def record(self, ok: bool) -> None:
        with self._lock:
            if ok:
                self.failures, self.opened_at = 0, None
                return
            self.failures += 1
            if self.threshold and self.failures >= self.threshold:
                self.opened_at = time.monotonic()


_BREAKERS: dict[str, CircuitBreaker] = {}
_BREAKERS_LOCK = threading.Lock()


def breaker_for(url: str) -> CircuitBreaker:
    """The breaker shared by every delegate that calls ``url`` in this process."""
    with _BREAKERS_LOCK:
        return _BREAKERS.setdefault(url, CircuitBreaker())


class A2ADelegate:
    """A sub-agent behind an A2A URL, callable like the in-process one.

    ``delegate(text)`` for synchronous code, ``await delegate.acall(text)`` for
    async code; both return the agent's answer as text.
    """

    def __init__(
        self,
        *,
        name: str,
        url: str,
        timeout: float = DEFAULT_TIMEOUT,
        retries: int = DEFAULT_RETRIES,
        backoff: float = RETRY_BACKOFF,
    ) -> None:
        self.name = name
        self.url = url
        self.timeout = timeout
        self.retries = retries
        self.backoff = backoff
        self.breaker = breaker_for(url)

    def __call__(self, request: str) -> str:
        self.breaker.check(self.name, self.url)
        with _span(self.name, self.url) as span:
            payload = _payload(request)
            with httpx.Client(timeout=self.timeout) as client:
                for attempt in range(self.retries + 1):
                    try:
                        response = client.post(self.url, json=payload, headers=_headers())
                    except httpx.HTTPError as exc:
                        if self._retry(attempt, exc, span):
                            time.sleep(self._wait(attempt))
                            continue
                        raise self._fail(_unreachable(self.name, self.url, exc)) from exc
                    if response.status_code in _RETRYABLE_STATUS and attempt < self.retries:
                        _note_retry(span, attempt)
                        time.sleep(self._wait(attempt))
                        continue
                    return self._answer(response, span)
        raise AssertionError("unreachable")  # pragma: no cover

    async def acall(self, request: str) -> str:
        self.breaker.check(self.name, self.url)
        with _span(self.name, self.url) as span:
            payload = _payload(request)
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                for attempt in range(self.retries + 1):
                    try:
                        response = await client.post(self.url, json=payload, headers=_headers())
                    except httpx.HTTPError as exc:
                        if self._retry(attempt, exc, span):
                            await asyncio.sleep(self._wait(attempt))
                            continue
                        raise self._fail(_unreachable(self.name, self.url, exc)) from exc
                    if response.status_code in _RETRYABLE_STATUS and attempt < self.retries:
                        _note_retry(span, attempt)
                        await asyncio.sleep(self._wait(attempt))
                        continue
                    return self._answer(response, span)
        raise AssertionError("unreachable")  # pragma: no cover

    # -- internals -----------------------------------------------------------

    def _retry(self, attempt: int, exc: Exception, span: Any) -> bool:
        """Only a request that never reached the agent is safe to send again."""
        if attempt >= self.retries or not isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout)):
            return False
        _note_retry(span, attempt)
        return True

    def _wait(self, attempt: int) -> float:
        return self.backoff * 2 ** attempt

    def _answer(self, response: httpx.Response, span: Any) -> str:
        # An agent that answers with an error is up; one that answers 5xx is not.
        self.breaker.record(ok=response.status_code < 500)
        return _read(response, self.name, self.url, span)

    def _fail(self, error: A2AError) -> A2AError:
        self.breaker.record(ok=False)
        return error

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


def _note_retry(span: Any, attempt: int) -> None:
    if span is not None:
        span.set_attribute("a2a.retries", attempt + 1)


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
