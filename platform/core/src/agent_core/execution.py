"""How long one invocation may run, how often it is retried, and what it costs.

``timeout_seconds`` and ``retry_attempts`` used to be declared, validated and
then ignored: every runtime streamed an answer for as long as the model took.
They are applied here, once, around ``Runtime.stream`` — the one seam the three
frameworks already share — so none of them has to learn about deadlines.

Retrying a stream is only safe while nothing has been yielded: once the caller
has printed half an answer, running the agent again would print a different
first half. And some failures are verdicts, not accidents — a guardrail that
blocked will block again — so those are never retried.

The cost side is plain arithmetic, framework-free too: the runtimes count tokens
the way their framework reports them and ask :func:`cost_usd` what that means.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, AsyncIterator, Callable

from .errors import (
    BuildError,
    ConfigError,
    GuardrailViolation,
    PermissionDeniedError,
    PlatformError,
)
from .telemetry import get_logger, log_event

logger = get_logger("execution")

#: Seconds before the first retry; doubles on each attempt.
RETRY_BACKOFF = 1.0

#: Failures that are decisions of the platform, not transient errors.
NOT_RETRYABLE: tuple[type[BaseException], ...] = (
    GuardrailViolation,
    PermissionDeniedError,
    ConfigError,
    BuildError,
)


class InvocationTimeout(PlatformError):
    """The invocation ran past the ``timeout_seconds`` of its policy."""


class BudgetExceeded(PermissionDeniedError):
    """The invocation spent its ``budget`` (tokens or dollars)."""


def guarded_stream(
    start: Callable[[], AsyncIterator[str]],
    *,
    timeout_seconds: float | None = None,
    retry_attempts: int = 0,
    agent: str = "",
    backoff: float = RETRY_BACKOFF,
) -> AsyncIterator[str]:
    """Stream ``start()`` under a deadline, retrying while nothing has been yielded.

    Args:
        start: Opens a fresh stream for each attempt (``lambda: runtime.stream(app, msg)``).
        timeout_seconds: Wall-clock limit for the whole invocation, retries included.
        retry_attempts: Extra attempts after the first one fails.
        agent: Name used in logs and error messages.
        backoff: Seconds before the first retry; doubles on each attempt.
    """

    async def stream() -> AsyncIterator[str]:
        deadline = time.monotonic() + timeout_seconds if timeout_seconds else None
        attempt = 0
        while True:
            yielded = False
            try:
                iterator = start().__aiter__()
                while True:
                    try:
                        chunk = await _next(iterator, deadline)
                    except StopAsyncIteration:
                        return
                    yielded = True
                    yield chunk
            except asyncio.TimeoutError:
                log_event(logger, "invocation timed out", agent=agent, limit=timeout_seconds)
                raise InvocationTimeout(
                    f"agent '{agent}' did not finish within its timeout of {timeout_seconds:g}s"
                ) from None
            except NOT_RETRYABLE:
                raise
            except Exception as exc:  # noqa: BLE001 - decide below whether to retry
                if yielded or attempt >= retry_attempts:
                    raise
                attempt += 1
                wait = backoff * 2 ** (attempt - 1)
                if deadline is not None and time.monotonic() + wait >= deadline:
                    raise
                log_event(logger, "retrying invocation", agent=agent, attempt=attempt,
                          error=f"{type(exc).__name__}: {exc}", wait=wait)
                await asyncio.sleep(wait)

    return stream()


def stream_with_policies(runtime: Any, app: Any, message: str, manifest: Any) -> AsyncIterator[str]:
    """``runtime.stream`` with the timeout and retries the manifest declared."""
    policies = getattr(getattr(manifest, "spec", None), "policies", None)
    return guarded_stream(
        lambda: runtime.stream(app, message),
        timeout_seconds=getattr(policies, "timeout_seconds", None),
        retry_attempts=getattr(policies, "retry_attempts", 0) or 0,
        agent=getattr(manifest, "name", ""),
    )


def cost_usd(pricing: Any, input_tokens: int, output_tokens: int) -> float | None:
    """Dollars spent for a token count, or ``None`` when the model has no price."""
    if pricing is None:
        return None
    return (input_tokens * pricing.input_per_mtok + output_tokens * pricing.output_per_mtok) / 1_000_000


def check_budget(agent: str, budget: Any, pricing: Any, input_tokens: int, output_tokens: int) -> None:
    """Raise :class:`BudgetExceeded` if the tokens spent so far exhaust ``budget``."""
    if budget is None:
        return
    total = input_tokens + output_tokens
    if budget.max_tokens and total >= budget.max_tokens:
        raise BudgetExceeded(f"agent '{agent}' spent its budget of {budget.max_tokens} tokens")
    if budget.max_usd is not None:
        spent = cost_usd(pricing, input_tokens, output_tokens)
        if spent is not None and spent >= budget.max_usd:
            raise BudgetExceeded(
                f"agent '{agent}' spent its budget of ${budget.max_usd:g} (${spent:.4f})"
            )


async def _next(iterator: AsyncIterator[str], deadline: float | None) -> str:
    if deadline is None:
        return await iterator.__anext__()
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise asyncio.TimeoutError
    return await asyncio.wait_for(iterator.__anext__(), timeout=remaining)
