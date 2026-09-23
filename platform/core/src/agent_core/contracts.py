"""Protocols implemented by runtime packages.

``agent-core`` never imports a runtime package. Instead it declares the shapes
that runtime packages must satisfy, and those packages advertise themselves
through entry points. This is what keeps the dependency graph acyclic:

    agent-core  <-  agent-runtime  <-  agent-runtime-{adk,langgraph,langchain}
                                            \\____________ discovers runtimes ____/

A **builder** turns a manifest into a framework object. A **runtime** is the
whole story for one framework: it builds, it wraps the result into whatever that
framework calls a runnable application, and it knows how to stream an answer out
of it. One runtime per framework, contributed as its own distribution.
"""

from __future__ import annotations

from typing import Any, AsyncIterator, Protocol, runtime_checkable

from .result import BuildResult


@runtime_checkable
class AgentBuilder(Protocol):
    """Turns a validated manifest into a framework-native agent object.

    One builder per manifest ``kind`` (``Agent``, ``Workflow``...) *and* per
    framework, which is how both a new orchestration shape and a new framework
    are added without touching anything that already works.
    """

    kind: str

    #: Framework this builder produces objects for (``adk``, ``langgraph``...).
    runtime: str

    def build(self, manifest: Any, factory: Any) -> BuildResult: ...


@runtime_checkable
class Runtime(Protocol):
    """One framework, end to end: build it, wrap it, run it.

    This is what was missing while there was only one framework. ``build_app``
    used to return an ADK ``App`` by name, so "run an agent" meant "run an ADK
    agent" and nothing else could be plugged in. Behind this protocol, the
    factory no longer knows which framework it is driving.
    """

    #: Short name used in ``spec.runtime`` and on the command line.
    name: str

    def app(self, result: BuildResult) -> Any:
        """Wrap a build into whatever this framework runs."""
        ...

    def stream(self, app: Any, message: str) -> AsyncIterator[str]:
        """Send one message and yield the answer as it arrives."""
        ...
