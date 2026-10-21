"""Static check for submitted strategy code.

This blocks the obvious ways a strategy could touch files, the network, the
shell or the process (imports, builtins, dunder tricks). It is NOT a security
sandbox. The real protection is that submitted code only ever runs in CI and
paper mode with no API keys, and that a person reviews it before it is merged
and deployed with live keys.
"""

from __future__ import annotations

import ast
import sys

ALLOWED_IMPORTS = {
    "math",
    "statistics",
    "dataclasses",
    "typing",
    "collections",
    "itertools",
    "functools",
    "enum",
    "__future__",
    "engine",
    "engine.strategy",
}
BANNED_NAMES = {
    "eval",
    "exec",
    "compile",
    "open",
    "__import__",
    "globals",
    "locals",
    "vars",
    "getattr",
    "setattr",
    "delattr",
    "input",
    "breakpoint",
    "exit",
    "quit",
    "memoryview",
    "help",
}
MAX_BYTES = 100_000


def check_source(src: str) -> list:
    """Returns a list of problems; empty means the code passed."""
    problems = []
    if len(src.encode("utf-8")) > MAX_BYTES:
        return [f"strategy.py is larger than {MAX_BYTES // 1000} KB"]
    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        return [f"Syntax error on line {e.lineno}: {e.msg}"]

    strategy_classes = 0
    for node in ast.walk(tree):
        line = getattr(node, "lineno", "?")
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name not in ALLOWED_IMPORTS:
                    problems.append(f"line {line}: import {a.name} is not allowed")
        elif isinstance(node, ast.ImportFrom):
            mod = ("." * node.level) + (node.module or "")
            if node.level or mod not in ALLOWED_IMPORTS:
                problems.append(f"line {line}: from {mod} import … is not allowed")
        elif isinstance(node, ast.Name) and node.id in BANNED_NAMES:
            problems.append(f"line {line}: {node.id} is not allowed")
        elif isinstance(node, ast.Attribute) and node.attr.startswith("__") and node.attr.endswith("__"):
            if node.attr not in ("__init__",):
                problems.append(f"line {line}: attribute {node.attr} is not allowed")
        elif isinstance(node, ast.Name) and node.id.startswith("__") and node.id not in ("__name__",):
            problems.append(f"line {line}: name {node.id} is not allowed")
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            problems.append(f"line {line}: global/nonlocal is not allowed; use ctx.state")
        elif isinstance(node, ast.ClassDef):
            for b in node.bases:
                name = b.attr if isinstance(b, ast.Attribute) else getattr(b, "id", "")
                if name == "Strategy":
                    strategy_classes += 1
    if strategy_classes != 1:
        problems.append(f"Define exactly one class that subclasses Strategy (found {strategy_classes})")
    return problems


def main() -> None:
    path = sys.argv[1]
    problems = check_source(open(path, encoding="utf-8").read())  # noqa: SIM115
    for p in problems:
        print(p)
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
