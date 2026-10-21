"""Print which bots a branch changed, for the CI workflow.

  python -m engine.changed --base origin/main   ->  bots=<names>  outside=<paths>
"""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    a = ap.parse_args()
    out = subprocess.run(["git", "diff", "--name-only", f"{a.base}...HEAD"], capture_output=True, text=True, check=True).stdout
    files = [f for f in out.splitlines() if f.strip()]
    bots, outside = set(), []
    for f in files:
        parts = Path(f).parts
        if len(parts) >= 3 and parts[0] == "bots":
            if (Path("bots") / parts[1]).is_dir():
                bots.add(parts[1])
        elif parts and parts[0] == "data":
            continue  # candle files are allowed
        else:
            outside.append(f)
    print(f"bots={' '.join(sorted(bots))}")
    print(f"outside={' '.join(outside)}")


if __name__ == "__main__":
    main()
