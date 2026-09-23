"""Deterministic merging and environment interpolation for configuration."""

from __future__ import annotations

import os
import re
from typing import Any, Mapping

from ..errors import ConfigError

# ${VAR} or ${VAR:-default}
_VAR_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")


def deep_merge(base: Any, override: Any) -> Any:
    """Merge ``override`` onto ``base``.

    Mappings merge key by key; every other type (including lists) is replaced.
    Lists are replaced on purpose: a merged tool list would make it impossible
    for an environment to *remove* a tool.
    """
    if isinstance(base, Mapping) and isinstance(override, Mapping):
        merged = dict(base)
        for key, value in override.items():
            merged[key] = deep_merge(merged[key], value) if key in merged else value
        return merged
    return override


def merge_all(*layers: Any) -> dict[str, Any]:
    """Merge configuration layers left to right; later layers win."""
    result: dict[str, Any] = {}
    for layer in layers:
        if layer:
            result = deep_merge(result, layer)
    return result


def interpolate(value: Any, env: Mapping[str, str] | None = None) -> Any:
    """Expand ``${VAR}`` / ``${VAR:-default}`` references in every string."""
    environment = os.environ if env is None else env

    def _expand(match: re.Match[str]) -> str:
        name, default = match.group(1), match.group(2)
        if name in environment:
            return environment[name]
        if default is not None:
            return default
        raise ConfigError(
            f"environment variable '{name}' is referenced by configuration but is not set "
            f"(use ${{{name}:-default}} to make it optional)"
        )

    if isinstance(value, str):
        return _VAR_RE.sub(_expand, value)
    if isinstance(value, Mapping):
        return {key: interpolate(item, environment) for key, item in value.items()}
    if isinstance(value, list):
        return [interpolate(item, environment) for item in value]
    return value


def render_template(text: str, variables: Mapping[str, str]) -> str:
    """Substitute ``{{ name }}`` placeholders in a prompt template."""
    def _replace(match: re.Match[str]) -> str:
        key = match.group(1).strip()
        if key not in variables:
            raise ConfigError(f"prompt references undefined variable '{key}'")
        return str(variables[key])

    return re.sub(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}", _replace, text)
