"""agent-runtime-adk: the Google ADK runtime of the platform.

One of three interchangeable runtimes. It contributes, through entry points:

* the builder for ``kind: Agent``    (manifest -> ``LlmAgent``)
* the builder for ``kind: Workflow`` (manifest -> ``Workflow`` / ``LoopAgent``)
* the ``adk`` runtime itself         (``App`` + streaming)

Nothing here is imported by name anywhere else. Installing the package is what
makes ``spec.runtime: adk`` work, and uninstalling it is what makes it stop.
"""

from .builder import AgentBuilder
from .runtime import AdkRuntime
from .version import __version__
from .workflow import WorkflowBuilder

__all__ = ["AdkRuntime", "AgentBuilder", "WorkflowBuilder", "__version__"]
