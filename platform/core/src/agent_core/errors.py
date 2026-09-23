"""Error hierarchy shared by every package of the platform."""


class PlatformError(Exception):
    """Base class for all platform errors."""


class ConfigError(PlatformError):
    """Raised when a manifest or configuration file is invalid or unresolvable."""


class RegistryError(PlatformError):
    """Raised when a component reference cannot be resolved in a registry."""


class PermissionDeniedError(PlatformError):
    """Raised when a component is used outside the permissions granted to an agent."""


class GuardrailViolation(PlatformError):
    """Raised when a guardrail with a blocking action matches."""


class BuildError(PlatformError):
    """Raised when a valid manifest cannot be turned into a runnable agent."""
