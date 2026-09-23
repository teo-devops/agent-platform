"""Las tools de los agentes de ingeniería: análisis estático, sin ejecutar nada."""

from __future__ import annotations

import pytest

SOURCE = '''
def load(path, cache={}):
    try:
        if cache.get(path) == None:
            print("miss")
    except:
        pass
    return eval(path)


def add(a: int, b: int) -> int:
    """Suma."""
    return a + b
'''


@pytest.fixture
def code(registries):
    return {name.split(".")[1]: registries.tools.get(name) for name in registries.tools.match("code.*")}


def test_syntax_errors_point_at_the_line(code):
    assert code["check_syntax"]("def f(:\n  pass") == {"valid": False, "line": 1, "column": 7, "message": "invalid syntax"}
    assert code["check_syntax"](SOURCE) == {"valid": True}


def test_metrics_per_function(code):
    functions = {f["name"]: f for f in code["metrics"](SOURCE)["functions"]}
    assert functions["add"]["fully_typed"] and functions["add"]["has_docstring"]
    assert not functions["load"]["fully_typed"] and functions["load"]["complexity"] > functions["add"]["complexity"]


def test_smells_are_found_with_their_lines(code):
    kinds = {s["kind"]: s["line"] for s in code["find_smells"](SOURCE)["smells"]}
    assert kinds == {"mutable-default": 2, "none-comparison": 4, "print": 5, "bare-except": 6, "dynamic-code": 8}


def test_code_that_does_not_parse_is_reported_not_raised(code):
    assert "error" in code["metrics"]("def (")
    assert "error" in code["find_smells"]("def (")
