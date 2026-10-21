TF_MS = {
    "1m": 60_000,
    "3m": 180_000,
    "5m": 300_000,
    "15m": 900_000,
    "30m": 1_800_000,
    "1h": 3_600_000,
    "2h": 7_200_000,
    "4h": 14_400_000,
    "6h": 21_600_000,
    "12h": 43_200_000,
    "1d": 86_400_000,
}


def tf_ms(tf: str) -> int:
    key = tf.strip().lower()
    if key not in TF_MS:
        raise ValueError(f"Unknown timeframe {tf!r}. Use one of: {', '.join(TF_MS)}")
    return TF_MS[key]
