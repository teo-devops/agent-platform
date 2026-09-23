"""agent-mlflow: MLflow as the AgentOps backend of the platform.

Four jobs, each one a question somebody asks about an agent in production:

* **Which prompt is running?** — :mod:`.prompts` registers every agent's prompt
  in the Prompt Registry, keyed by its hash, so a version number means one text.
* **Which agent version answered?** — :mod:`.models` records each
  ``name@version`` as a ``LoggedModel`` with its model, framework, tools and
  skills; :mod:`.traces` tags every trace with the agent, version and prompt
  that produced it.
* **Is v2 better than v1?** — :mod:`.evals` publishes ``agentctl eval`` results
  as runs attached to the agent version, with a row and a trace per case.
* **How does it behave?** — :mod:`.traces` turns traces into latency, tokens and
  tool calls per agent version, prompt version and framework.

Configured with the standard ``MLFLOW_TRACKING_URI``.
"""

import os

# MLflow prints a hint for coding assistants on import; it is noise in a CLI.
os.environ.setdefault("MLFLOW_DISABLE_AGENT_HINT", "1")

from .version import __version__  # noqa: E402

__all__ = ["__version__"]
