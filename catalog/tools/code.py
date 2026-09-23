"""Static analysis of Python code: the tools of the engineering agents.

Pure functions over the source text — nothing is imported, executed or written
to disk, so a model can call them on any code it is handed without risk. They
are what lets a reviewer ground its findings in facts ("cyclomatic complexity
9") instead of impressions.
"""

from __future__ import annotations

import ast

#: Above this many decision points a function is worth splitting.
COMPLEXITY_THRESHOLD = 10
#: Above this many lines a function is worth splitting.
LENGTH_THRESHOLD = 40

_BRANCHES = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.Try, ast.With, ast.AsyncWith,
             ast.ExceptHandler, ast.IfExp, ast.comprehension, ast.Assert, ast.Match)


def check_syntax(code: str) -> dict:
    """Checks whether a piece of Python code parses, without running it.

    Args:
        code: The Python source code to check.

    Returns:
        A dict with 'valid' (bool) and, when invalid, the 'line', 'column' and
        'message' of the first syntax error.
    """
    try:
        ast.parse(code)
    except SyntaxError as exc:
        return {"valid": False, "line": exc.lineno, "column": exc.offset, "message": exc.msg}
    return {"valid": True}


def metrics(code: str) -> dict:
    """Measures each function in Python code: length, complexity, docstring and type hints.

    Args:
        code: The Python source code to measure.

    Returns:
        A dict with one entry per function under 'functions' (name, lines,
        cyclomatic 'complexity', 'has_docstring', 'fully_typed') and the
        names of the functions over the complexity or length thresholds
        under 'hotspots'. An 'error' key is returned if the code does not parse.
    """
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return {"error": f"syntax error at line {exc.lineno}: {exc.msg}"}

    functions = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        arguments = [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]
        typed = all(a.annotation is not None for a in arguments if a.arg not in ("self", "cls"))
        functions.append({
            "name": node.name,
            "lines": (node.end_lineno or node.lineno) - node.lineno + 1,
            "complexity": 1 + sum(isinstance(n, _BRANCHES) or isinstance(n, ast.BoolOp) for n in ast.walk(node)),
            "has_docstring": ast.get_docstring(node) is not None,
            "fully_typed": typed and node.returns is not None,
        })
    hotspots = [f["name"] for f in functions
                if f["complexity"] > COMPLEXITY_THRESHOLD or f["lines"] > LENGTH_THRESHOLD]
    return {"functions": functions, "hotspots": hotspots}


def find_smells(code: str) -> dict:
    """Finds common Python code smells and risky constructs, with their line numbers.

    Looks for bare 'except:', mutable default arguments, eval/exec, 'print'
    left in library code, wildcard imports and comparisons to None with '=='.

    Args:
        code: The Python source code to inspect.

    Returns:
        A dict with a 'smells' list; each item has 'line', 'kind' and a short
        'detail'. An 'error' key is returned if the code does not parse.
    """
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return {"error": f"syntax error at line {exc.lineno}: {exc.msg}"}

    smells = []

    def add(node: ast.AST, kind: str, detail: str) -> None:
        smells.append({"line": getattr(node, "lineno", 0), "kind": kind, "detail": detail})

    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler) and node.type is None:
            add(node, "bare-except", "catches everything, including KeyboardInterrupt")
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for default in [*node.args.defaults, *node.args.kw_defaults]:
                if isinstance(default, (ast.List, ast.Dict, ast.Set)):
                    add(default, "mutable-default", f"'{node.name}' shares one default object across calls")
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in ("eval", "exec"):
                add(node, "dynamic-code", f"{node.func.id}() runs arbitrary code")
            elif node.func.id == "print":
                add(node, "print", "use logging in library code")
        elif isinstance(node, ast.ImportFrom) and any(alias.name == "*" for alias in node.names):
            add(node, "wildcard-import", f"from {node.module} import *")
        elif isinstance(node, ast.Compare):
            for op, right in zip(node.ops, node.comparators):
                if isinstance(op, (ast.Eq, ast.NotEq)) and isinstance(right, ast.Constant) and right.value is None:
                    add(node, "none-comparison", "use 'is None' / 'is not None'")
    return {"smells": sorted(smells, key=lambda s: s["line"])}
