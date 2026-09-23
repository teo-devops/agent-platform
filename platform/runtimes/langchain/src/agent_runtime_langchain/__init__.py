"""agent-runtime-langchain: the LangChain runtime of the platform.

The third reading of the same manifests. ADK builds an ``LlmAgent``, LangGraph a
``StateGraph``, and this builds a ``create_agent`` with middleware, composing
workflows as LCEL chains. Where LCEL cannot express what the manifest asks for —
a real graph, a loop — the build says so rather than approximating.
"""

from .builder import AgentBuilder
from .runtime import LangChainRuntime
from .version import __version__
from .workflow import WorkflowBuilder

__all__ = ["AgentBuilder", "LangChainRuntime", "WorkflowBuilder", "__version__"]
