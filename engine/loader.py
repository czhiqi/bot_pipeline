"""Load a bot's Strategy subclass from bots/<name>/strategy.py."""

from __future__ import annotations

import importlib.util
import inspect
import sys
from pathlib import Path

from .strategy import Strategy


def load_strategy_class(bot_dir: str | Path):
    path = Path(bot_dir) / "strategy.py"
    if not path.exists():
        raise FileNotFoundError(f"{path} not found")
    mod_name = f"bot_strategy_{Path(bot_dir).name.replace('-', '_')}"
    spec = importlib.util.spec_from_file_location(mod_name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module
    spec.loader.exec_module(module)
    found = [
        obj
        for obj in vars(module).values()
        if inspect.isclass(obj) and issubclass(obj, Strategy) and obj is not Strategy and obj.__module__ == mod_name
    ]
    if len(found) != 1:
        raise ValueError(f"strategy.py must define exactly one Strategy subclass (found {len(found)})")
    return found[0]


def build_strategy(bot_dir: str | Path, cfg: dict) -> Strategy:
    cls = load_strategy_class(bot_dir)
    return cls(cfg.get("params") or {})
