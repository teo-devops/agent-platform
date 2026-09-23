"""agent-core: the versioned, reusable foundation of the agent platform.

This package deliberately has **no dependency on Google ADK**. It only defines:

* the declarative schemas of the platform (``agent_core.schemas``),
* how configuration is discovered, merged and resolved (``agent_core.config``),
* how components are registered and looked up (``agent_core.registry``),
* the protocols that runtime packages implement (``agent_core.contracts``),
* framework-agnostic guardrail evaluation (``agent_core.guardrails``).

Keeping the core framework-free is what allows the runtime (ADK today, anything
else tomorrow) to be swapped without touching agent configuration.
"""

from .errors import (
    BuildError,
    ConfigError,
    GuardrailViolation,
    PermissionDeniedError,
    PlatformError,
    RegistryError,
)
from .registry import Registry
from .version import API_VERSION, __version__

__all__ = [
    "API_VERSION",
    "BuildError",
    "ConfigError",
    "GuardrailViolation",
    "PermissionDeniedError",
    "PlatformError",
    "Registry",
    "RegistryError",
    "__version__",
]
