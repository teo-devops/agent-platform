"""LangChain as a platform runtime."""

from __future__ import annotations

from typing import Any, AsyncIterator

from agent_core.result import BuildResult


class LangChainRuntime:
    """The ``langchain`` runtime: agents and LCEL chains, invoked and streamed."""

    name = "langchain"

    def app(self, result: BuildResult) -> Any:
        """A runnable is already runnable; the middleware is inside the agent."""
        return result.agent

    async def stream(self, app: Any, message: str) -> AsyncIterator[str]:
        """Send one message and yield the answer.

        A chain built from a workflow takes and returns plain text; an agent
        takes and returns messages. The result says which one answered.
        """
        payload: Any = {"messages": [{"role": "user", "content": message}]}
        if not _takes_messages(app):
            payload = {"inputs": {"message": message}, "outputs": {}}

        answer = await app.ainvoke(payload)

        if isinstance(answer, str):
            yield answer
        elif isinstance(answer, dict) and "messages" in answer:
            messages = answer["messages"]
            # `.text`, not `.content`: Gemini answers with a list of blocks.
            yield messages[-1].text if messages else ""
        elif isinstance(answer, dict):
            yield "\n\n".join(f"{key}:\n{value}" for key, value in answer.items())
        else:
            yield str(answer)


def _takes_messages(app: Any) -> bool:
    """Whether ``app`` is an agent (reads ``messages``) rather than a workflow chain.

    Read from the input JSON Schema: the schema *class* of a compiled agent is
    named after the agent (``code_reviewer_input``), so its ``str()`` says nothing.
    """
    try:
        return "messages" in (app.get_input_jsonschema().get("properties") or {})
    except Exception:  # noqa: BLE001 - a runnable without a schema is not an agent
        return False
