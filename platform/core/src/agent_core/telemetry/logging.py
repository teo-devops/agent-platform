"""Minimal structured logging shared by the platform packages."""

from __future__ import annotations

import json
import logging
import os
from typing import Any

_CONFIGURED = False


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "level": record.levelname.lower(),
            "logger": record.name,
            "message": record.getMessage(),
        }
        payload.update(getattr(record, "context", {}) or {})
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure(level: str | None = None, *, json_output: bool | None = None) -> None:
    """Configure the ``agent`` logger tree once per process."""
    global _CONFIGURED
    if _CONFIGURED:
        return
    level = (level or os.getenv("AGENT_LOG_LEVEL", "INFO")).upper()
    use_json = os.getenv("AGENT_LOG_FORMAT", "text").lower() == "json" if json_output is None else json_output

    handler = logging.StreamHandler()
    handler.setFormatter(_JsonFormatter() if use_json else logging.Formatter("%(levelname)-7s %(name)s | %(message)s"))

    root = logging.getLogger("agent")
    root.handlers = [handler]
    root.setLevel(level)
    root.propagate = False
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    """Return a namespaced logger, configuring the tree on first use."""
    configure()
    return logging.getLogger(f"agent.{name}")


def log_event(logger: logging.Logger, message: str, **context: Any) -> None:
    """Log a message with structured context attached."""
    logger.info(message, extra={"context": context})
