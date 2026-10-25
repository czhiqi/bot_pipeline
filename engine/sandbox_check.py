"""Static check for submitted strategy code (Forge on_candle strategies and
research-lab build_signal strategies).

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
    # research-lab strategies (vectorized build_signal, see engine/signal_adapter.py)
    "numpy",
    "pandas",
    "tool",
    "tool.engine",
}
# pandas/numpy reach files, the shell (via pickle) and string evaluation through
# these methods; a strategy never needs them. Matched as attribute names, so
# `pd.read_csv`, `df.to_pickle`, `np.load` and `df.eval` are all rejected.
BANNED_ATTRS = {
    "eval", "query", "to_pickle", "read_pickle", "to_csv", "to_parquet", "to_json", "to_sql", "to_excel",
    "to_hdf", "to_feather", "to_html", "to_xml", "to_clipboard", "to_stata", "to_latex", "to_orc", "to_markdown",
    "load", "save", "savez", "savez_compressed", "fromfile", "tofile", "memmap", "loadtxt", "savetxt",
    "genfromtxt", "fromregex", "DataSource", "ctypeslib", "f2py", "io", "testing", "util", "system",
}
LAB_REQUIRED = ("SYMBOL", "TIMEFRAME", "DATASET", "PARAMS")
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
    lab_classes = 0
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
        elif isinstance(node, ast.Attribute) and (node.attr in BANNED_ATTRS or node.attr.startswith("read_")):
            problems.append(f"line {line}: .{node.attr} is not allowed (file access or code evaluation)")
        elif isinstance(node, ast.Name) and node.id.startswith("__") and node.id not in ("__name__",):
            problems.append(f"line {line}: name {node.id} is not allowed")
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            problems.append(f"line {line}: global/nonlocal is not allowed; use ctx.state")
        elif isinstance(node, ast.ClassDef):
            for b in node.bases:
                name = b.attr if isinstance(b, ast.Attribute) else getattr(b, "id", "")
                if name == "Strategy":
                    strategy_classes += 1
            if _is_lab_class(node):
                lab_classes += 1
    if strategy_classes > 1 or (strategy_classes == 0 and lab_classes != 1):
        problems.append(
            "Define exactly one class that subclasses Strategy, or exactly one research-lab strategy class "
            f"(SYMBOL, TIMEFRAME, DATASET, PARAMS, build_signal) -- found {strategy_classes} and {lab_classes}"
        )
    return problems


def _is_lab_class(node: ast.ClassDef) -> bool:
    names = set()
    has_build_signal = False
    for item in node.body:
        if isinstance(item, ast.Assign):
            names.update(t.id for t in item.targets if isinstance(t, ast.Name))
        elif isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
            names.add(item.target.id)
        elif isinstance(item, ast.FunctionDef) and item.name == "build_signal":
            has_build_signal = True
    return has_build_signal and all(n in names for n in LAB_REQUIRED)


def main() -> None:
    path = sys.argv[1]
    problems = check_source(open(path, encoding="utf-8").read())  # noqa: SIM115
    for p in problems:
        print(p)
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
