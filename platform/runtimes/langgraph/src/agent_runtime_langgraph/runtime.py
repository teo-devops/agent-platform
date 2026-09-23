"""LangGraph as a platform runtime."""

from __future__ import annotations

from typing import Any, AsyncIterator

from agent_core.result import BuildResult

#: Key the workflow graph reads its entry parameter from.
ENTRY_INPUT = "message"


class LangGraphRuntime:
    """The ``langgraph`` runtime: compiled graphs, invoked and streamed."""

    name = "langgraph"

    def app(self, result: BuildResult) -> Any:
        """A compiled graph is already runnable; there is no wrapper to add.

        The enforcement stack is not attached here the way ADK attaches plugins
        to an ``App``: on LangGraph it is already inside the graph, wired into
        the model hooks when the agent was built.
        """
        return result.agent

    async def stream(self, app: Any, message: str) -> AsyncIterator[str]:
        """Send one message and yield the final answer.

        Workflows and agents take different inputs — a graph of steps reads
        ``inputs``, a react agent reads ``messages`` — so the shape of the state
        decides which is which.
        """
        payload = _payload(app, message)
        state = await app.ainvoke(payload)

        if "outputs" in state:
            last = list(state["outputs"].values())
            yield last[-1] if last else ""
            return

        messages = state.get("messages", [])
        # `.text`, not `.content`: Gemini answers with a list of blocks (text
        # plus a thought signature), and only the text is the answer.
        yield messages[-1].text if messages else ""


def _payload(app: Any, message: str) -> dict[str, Any]:
    schema = getattr(app, "stream_channels_list", None) or []
    if "outputs" in schema or "inputs" in schema:
        return {"inputs": {ENTRY_INPUT: message}, "outputs": {}, "iteration": 0}
    return {"messages": [{"role": "user", "content": message}]}
