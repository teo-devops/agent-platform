"""agent-runtime: the framework-free host of the platform.

It finds the configuration tree, assembles the context, resolves which runtime
should build a manifest, and exposes ``agentctl``. It does **not** know how any
framework works — ADK, LangGraph and LangChain each arrive as their own
distribution and announce themselves through entry points.

Typical use::

    from agent_runtime import AgentFactory, load_platform

    factory = load_platform(environment="local")
    app = factory.build_app("health-advisor")
"""

from agent_core.result import BuildResult

from .context import PlatformContext, load_platform
from .factory import AgentFactory
from .version import __version__

__all__ = [
    "AgentFactory",
    "BuildResult",
    "PlatformContext",
    "__version__",
    "load_platform",
]
