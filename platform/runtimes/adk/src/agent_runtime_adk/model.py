"""Translation of ``spec.model`` into ADK model settings."""

from __future__ import annotations

from agent_core.errors import ConfigError
from agent_core.schemas import ModelSpec
from google.genai import types


def resolve_model(spec: ModelSpec) -> tuple[str, types.GenerateContentConfig | None]:
    """Return the model name and the generation config declared by ``spec``.

    Raises:
        ConfigError: if neither the manifest nor its profile names a model.
    """
    if not spec.name:
        hint = f" (profile '{spec.profile}' does not define one)" if spec.profile else ""
        raise ConfigError(f"model.name is required{hint}: set it in the manifest or in configs/models.yaml")

    settings = {
        "temperature": spec.temperature,
        "top_p": spec.top_p,
        "top_k": spec.top_k,
        "max_output_tokens": spec.max_output_tokens,
        "stop_sequences": spec.stop_sequences or None,
    }
    settings = {key: value for key, value in settings.items() if value is not None}
    config = types.GenerateContentConfig(**settings) if settings else None
    return spec.name, config
