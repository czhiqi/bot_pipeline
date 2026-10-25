"""What `from tool.engine import ...` resolves to inside a lab strategy run by
Forge (installed by engine/loader.py). Same names the lab's own shim exposes
for strategy code: FeatureScale and friends, plus the ready-made templates."""
from .primitive import FeatureScale, NAFrame, SignalFn, SignalOutput  # noqa: F401
from .template import (  # noqa: F401
    abv_blw_dev, abv_blw_ma, abv_blw_zscore, allow_quantile, donchian_breakout, ma_crossover,
)

BARS_PER_DAY = {'1h': 24, '4h': 6, '1d': 1}
