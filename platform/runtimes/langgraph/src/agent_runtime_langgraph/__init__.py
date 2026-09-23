"""agent-runtime-langgraph: the LangGraph runtime of the platform.

Reads exactly the same manifests as the ADK runtime. Where ADK builds an
``LlmAgent`` inside an ``App``, this builds a compiled ``StateGraph``; where ADK
enforces guardrails through an app-level plugin, this uses the model hooks
LangGraph offers. The manifest does not change — only ``spec.runtime`` does.
"""

from .builder import AgentBuilder
from .runtime import LangGraphRuntime
from .version import __version__
from .workflow import WorkflowBuilder

__all__ = ["AgentBuilder", "LangGraphRuntime", "WorkflowBuilder", "__version__"]
