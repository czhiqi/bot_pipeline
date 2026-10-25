"""Load a bot's strategy from bots/<name>/strategy.py.

Two kinds of file are accepted:
  - a Forge strategy: exactly one engine.Strategy subclass (on_candle)
  - a research-lab strategy: no Strategy subclass, exactly one class with
    SYMBOL / TIMEFRAME / DATASET / PARAMS and build_signal; it is wrapped in
    engine.signal_adapter.SignalStrategy, and `from tool.engine import ...`
    inside it resolves to the vendored lab primitives (engine/lab/)
"""

from __future__ import annotations

import importlib.util
import inspect
import sys
import types
from pathlib import Path

from .strategy import Strategy


def _install_tool_engine_shim() -> None:
    from .lab import tool_engine

    if "tool" not in sys.modules:
        sys.modules["tool"] = types.ModuleType("tool")
    sys.modules["tool"].engine = tool_engine
    sys.modules["tool.engine"] = tool_engine


def _load_module(bot_dir: str | Path):
    path = Path(bot_dir) / "strategy.py"
    if not path.exists():
        raise FileNotFoundError(f"{path} not found")
    _install_tool_engine_shim()
    mod_name = f"bot_strategy_{Path(bot_dir).name.replace('-', '_')}"
    spec = importlib.util.spec_from_file_location(mod_name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module
    spec.loader.exec_module(module)
    return module, mod_name


def load_strategy_class(bot_dir: str | Path):
    """The Strategy subclass, or (for a lab file) the lab class itself."""
    from .signal_adapter import is_lab_strategy

    module, mod_name = _load_module(bot_dir)
    local = [obj for obj in vars(module).values() if inspect.isclass(obj) and obj.__module__ == mod_name]
    forge = [c for c in local if issubclass(c, Strategy) and c is not Strategy]
    if len(forge) == 1:
        return forge[0]
    if forge:
        raise ValueError(f"strategy.py must define exactly one Strategy subclass (found {len(forge)})")
    lab = [c for c in local if is_lab_strategy(c)]
    if len(lab) == 1:
        return lab[0]
    raise ValueError(
        "strategy.py must define exactly one engine.Strategy subclass, or exactly one research-lab strategy class "
        f"(SYMBOL, TIMEFRAME, DATASET, PARAMS, build_signal) -- found {len(lab)} lab classes"
    )


def build_strategy(bot_dir: str | Path, cfg: dict) -> Strategy:
    from .signal_adapter import SignalStrategy, is_lab_strategy

    cls = load_strategy_class(bot_dir)
    if is_lab_strategy(cls):
        return SignalStrategy(cls, cfg.get("params") or {}, timeframe=cfg["timeframe"])
    return cls(cfg.get("params") or {})
