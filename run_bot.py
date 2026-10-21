"""Start one bot.

  python run_bot.py bots/<name>             paper trading (default, safe)
  MODE=live ALLOW_LIVE=true in .env         real orders on the exchange

Settings and keys are read from .env in this folder (see .env.example).
Create a file named KILL in the bot folder to close the position and stop.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path


def load_env(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    bot_dir = Path(sys.argv[1])
    load_env(Path(".env"))
    load_env(bot_dir / ".env")  # optional per-bot keys
    (bot_dir / "logs").mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.StreamHandler(), logging.FileHandler(bot_dir / "logs" / "bot.log", encoding="utf-8")],
    )
    from engine.config import load_bot_config
    from engine.live import run_forever

    run_forever(str(bot_dir), load_bot_config(bot_dir))


if __name__ == "__main__":
    main()
