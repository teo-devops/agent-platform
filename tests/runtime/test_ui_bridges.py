"""Los puentes de cada playground construyen el mismo agente que `agentctl run`.

El carril local de la demo abre `python-developer` en ADK Dev UI y en LangGraph Studio
(para LangGraph y para LangChain). Aquí se comprueba, sin abrir nada ni llamar
al modelo, que cada puente generado construye ese agente con su skill.
"""

from __future__ import annotations

import importlib.util
import sys

import pytest
from agent_runtime import ui


def _import(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_adk_bridge_is_one_app_per_manifest_with_the_plugins(root, monkeypatch):
    """`adk web` lista todo el catálogo, y cada app lleva el enforcement."""
    monkeypatch.setenv("GOOGLE_API_KEY", "test")
    names = ["python-developer", "parallel-briefing"]
    target = root / ui.GENERATED_DIR / "adk_apps_test"
    try:
        for name in names:
            folder = target / ui._identifier(name)
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "agent.py").write_text(ui._adk_module(name, "local"), encoding="utf-8")

        module = _import(target / "python_developer" / "agent.py", "adk_bridge_developer")
        assert module.app.name == "python_developer"  # = the folder, as adk web expects
        assert any("skill" in getattr(t, "name", "") for t in module.root_agent.tools)
        plugins = {type(p).__name__ for p in module.app.plugins}
        assert {"GuardrailPlugin", "ToolPermissionPlugin", "PolicyPlugin"} <= plugins

        workflow = _import(target / "parallel_briefing" / "agent.py", "adk_bridge_workflow")
        assert workflow.app.name == "parallel_briefing"
    finally:
        import shutil

        shutil.rmtree(target, ignore_errors=True)


@pytest.mark.parametrize("runtime", ["langgraph", "langchain"])
def test_studio_bridge_exposes_each_agent_as_a_graph(root, monkeypatch, runtime):
    # Sin clave: Studio tiene que poder dibujar los grafos igualmente. La clave
    # sólo hace falta para llamar al modelo.
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    module_path = root / ui.GENERATED_DIR / "langgraph_app" / f"graphs_{runtime}_test.py"
    module_path.parent.mkdir(parents=True, exist_ok=True)
    module_path.write_text(ui._graph_module(runtime, "local", ["python-developer", "software-manager"]), encoding="utf-8")
    try:
        module = _import(module_path, f"studio_bridge_{runtime}")
        graph = module.python_developer()
        assert hasattr(graph, "ainvoke")
        nodes = set(graph.get_graph().nodes)
        assert "tools" in nodes or any("tool" in n for n in nodes)
        assert hasattr(module.software_manager(), "ainvoke")
    finally:
        module_path.unlink()
