"""agent-kagent: the catalogue, operated by kagent.

kagent is a *runtime* in the platform sense: it deploys agents as Kubernetes
resources, exposes each one over A2A, gives them a UI and ships their traces.
It is not a framework: it does not care how an agent was written.

This package is the bridge, in two directions:

* ``render`` turns ``agents.platform/v1`` manifests into kagent CRDs, so the
  manifest stays the single source of truth. A manifest becomes either a
  **Declarative** agent (kagent builds and runs it; nothing of ours runs) or a
  **BYO** agent (our runtime runs it inside kagent's pod contract).
* ``host`` is what runs inside a BYO pod: it builds the agent from the same
  manifest and serves it with kagent's A2A SDK.
"""

from .release import AgentRelease, Release
from .render import Rendered, render
from .version import __version__

__all__ = ["AgentRelease", "Release", "Rendered", "__version__", "render"]
