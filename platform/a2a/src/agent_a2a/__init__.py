"""agent-a2a: agents of the catalogue over the Agent2Agent protocol.

Two halves of the same protocol:

- **server** — any catalogue agent, on any framework, answering A2A
  ``message/send`` with an agent card at ``/.well-known/agent-card.json``.
  ``agentctl a2a serve``. What kagent's BYO host does inside a pod, without
  kagent: so the delegation between agents can be seen on a laptop.
- **client** — :class:`A2ADelegate`, the transport a builder uses when the
  environment says a sub-agent runs elsewhere (``a2a.endpoints`` or
  ``AGENT_A2A_ENDPOINTS``). The coordinator's manifest does not change: it still
  says ``sub_agents: [{ref: python-developer, mode: tool}]``.

The client speaks plain JSON-RPC over ``httpx`` — the protocol is the contract,
and the same few lines reach an agent served here or one behind kagent's
controller.
"""

from .client import A2ADelegate, fetch_card, send
from .version import __version__

__all__ = ["A2ADelegate", "__version__", "fetch_card", "send"]
