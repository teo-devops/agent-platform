"""A workflow's shape, as names, before any framework touches it.

Turning ``type: sequential`` into a list of edges is the same operation whether
the result becomes an ADK graph, a LangGraph ``StateGraph`` or a LangChain
chain. So it happens once, here, on plain strings — and each runtime maps those
names onto its own node objects.

This is what makes ``sequential``/``parallel``/``graph`` portable. ``loop`` is
not in this module because repetition is not an edge: each framework expresses
it differently, and flattening it would lose the stopping condition.
"""

from __future__ import annotations

from .errors import BuildError
from .schemas import WorkflowBody
from .schemas.workflow import START

Edge = tuple[str, str]


def edges(body: WorkflowBody) -> list[Edge]:
    """The workflow's edges as ``(origen, destino)`` name pairs.

    ``START`` marks an entry point. An author who wrote ``needs`` by hand gets
    exactly what they wrote; otherwise the shape declared in ``type`` decides.
    """
    names = [node.name for node in body.nodes]

    if any(node.needs for node in body.nodes):
        return _from_needs(body)

    if body.type == "graph":
        return _from_edges(body)

    if body.type == "parallel":
        return [(START, name) for name in names]

    # sequential, and each iteration of a loop
    return [(START, names[0])] + [
        (names[index], names[index + 1]) for index in range(len(names) - 1)
    ]


def _from_needs(body: WorkflowBody) -> list[Edge]:
    result: list[Edge] = []
    for node in body.nodes:
        if not node.needs:
            result.append((START, node.name))
        else:
            result.extend((dependency, node.name) for dependency in node.needs)
    return result


def _from_edges(body: WorkflowBody) -> list[Edge]:
    known = {node.name for node in body.nodes}
    result: list[Edge] = []
    for edge in body.edges:
        for endpoint in (edge.from_, edge.to):
            if endpoint != START and endpoint not in known:
                raise BuildError(f"workflow edge references unknown node '{endpoint}'")
        result.append((edge.from_, edge.to))
    return result


def entry_points(body: WorkflowBody) -> list[str]:
    """Nodes the workflow starts from."""
    return [target for origin, target in edges(body) if origin == START]
