"""El host BYO: lo que kagent recibe del grafo tiene que poder publicarlo.

kagent sólo publica el texto de un AIMessage cuyo content es un str. Gemini, tras
llamar a una tool, contesta con una lista de bloques (texto y firma de
pensamiento): sin aplanarla, la respuesta del agente no llegaba a A2A.
"""

from __future__ import annotations

import pytest
from agent_kagent.host import TextAnswers
from langchain_core.messages import AIMessage, ToolMessage


class _Graph:
    def __init__(self, events):
        self.events = events
        self.name = "python-developer"

    async def astream(self, payload, config=None, stream_mode=None):
        assert stream_mode == "updates"
        for event in self.events:
            yield event


async def _collect(graph):
    return [event async for event in graph.astream({}, {}, stream_mode="updates")]


@pytest.mark.asyncio
async def test_an_answer_in_blocks_reaches_kagent_as_text():
    blocks = [{"type": "text", "text": "def suma(a: int, b: int) -> int: ..."},
              {"type": "text", "text": "", "extras": {"signature": "abc"}}]
    answer = AIMessage(content=blocks)
    (event,) = await _collect(TextAnswers(_Graph([{"agent": {"messages": [answer]}}])))
    flat = event["agent"]["messages"][0]
    assert flat.content == "def suma(a: int, b: int) -> int: ..."
    assert answer.content == blocks  # el estado del grafo no se toca


@pytest.mark.asyncio
async def test_everything_else_passes_through_unchanged():
    call = AIMessage(content="", tool_calls=[{"id": "1", "name": "code_check_syntax", "args": {"code": "x"}}])
    tool = ToolMessage(content='{"valid": true}', tool_call_id="1")
    events = [{"agent": {"messages": [call]}}, {"tools": {"messages": [tool]}}, {"__interrupt__": ()}]
    assert await _collect(TextAnswers(_Graph(events))) == events


def test_the_rest_of_the_graph_is_the_graph():
    assert TextAnswers(_Graph([])).name == "python-developer"
