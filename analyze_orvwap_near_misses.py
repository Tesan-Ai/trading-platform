"""Analyze ORVWAP near-miss signals and estimate relaxed-filter impact."""

import argparse
from collections import Counter

import pandas as pd

import config
from strategies.opening_range_vwap_momentum import OpeningRangeVwapMomentumStrategy


def load_signals(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    return df[df["event_type"] == "SIGNAL"].copy()


def rule_failures(row: pd.Series, strategy: OpeningRangeVwapMomentumStrategy) -> list[str]:
    features = {
        "or_complete": True,
        "opening_range_high": row["opening_range_high"],
        "close": row["price"],
        "above_vwap": float(row["price"]) > float(row["vwap"]),
        "volume_ratio": float(row["volume_ratio"]),
        "spread_percent": float(row["spread"]),
        "distance_from_vwap_atr": row["distance_from_vwap_atr"],
    }
    regime = {
        "trade_allowed": bool(row["spy_above_vwap"]),
        "qqq_above_vwap": bool(row["qqq_above_vwap"]),
    }

    failures = []
    if row["ticker"] not in strategy.UNIVERSE:
        failures.append("universe")
    if not strategy._passed_opening_range_breakout(features):
        failures.append("or_breakout")
    if not features["above_vwap"]:
        failures.append("above_vwap")
    if features["volume_ratio"] < float(config.ORVWAP_MIN_VOLUME_RATIO):
        failures.append("volume_ratio")
    if features["spread_percent"] > float(config.ORVWAP_MAX_SPREAD_PCT):
        failures.append("spread")
    if pd.notna(features["distance_from_vwap_atr"]) and float(features["distance_from_vwap_atr"]) > float(
        config.ORVWAP_MAX_VWAP_EXTENSION_ATR
    ):
        failures.append("vwap_extension")
    if not regime["trade_allowed"]:
        failures.append("market_filter")
    if row["ticker"] in strategy.TECH_SYMBOLS and not regime["qqq_above_vwap"]:
        failures.append("qqq_filter")
    return failures


def simulate(df: pd.DataFrame, strategy: OpeningRangeVwapMomentumStrategy) -> tuple[int, Counter]:
    passes = 0
    failures = Counter()
    for _, row in df.iterrows():
        failed = rule_failures(row, strategy)
        if not failed:
            passes += 1
        else:
            failures[failed[0]] += 1
    return passes, failures


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--signal-log", default=config.ORVWAP_SIGNAL_LOG_FILE)
    args = parser.parse_args()

    df = load_signals(args.signal_log)
    strategy = OpeningRangeVwapMomentumStrategy()

    df["failures"] = df.apply(lambda row: rule_failures(row, strategy), axis=1)
    df["fail_count"] = df["failures"].apply(len)

    print("NEAR-MISS ANALYSIS")
    print("==================")
    print(f"Signals analyzed: {len(df)}")
    print("\nSingle-rule failures:")
    near = df[df["fail_count"] == 1]
    for rule, group in near.groupby(near["failures"].apply(lambda items: items[0])):
        print(f"  {rule}: {len(group)}")

    or_miss = df[df["failures"].apply(lambda items: items == ["or_breakout"])].copy()
    if not or_miss.empty:
        or_miss["or_gap_pct"] = (
            (or_miss["opening_range_high"] - or_miss["price"]) / or_miss["opening_range_high"] * 100
        )
        print("\nClosest OR near misses:")
        cols = ["timestamp", "ticker", "price", "opening_range_high", "or_gap_pct", "volume_ratio"]
        print(or_miss.nsmallest(10, "or_gap_pct")[cols].to_string(index=False))

    scenarios = [
        ("strict baseline", {}),
        ("relaxed test A: vol 1.2 + OR 0.05%", {"ORVWAP_MIN_VOLUME_RATIO": 1.2, "ORVWAP_OR_BREAKOUT_BUFFER_PCT": 0.05}),
        ("relaxed test B: vol 1.2 + OR 0.10%", {"ORVWAP_MIN_VOLUME_RATIO": 1.2, "ORVWAP_OR_BREAKOUT_BUFFER_PCT": 0.10}),
        (
            "relaxed test C: vol 1.2 + OR 0.05% + VWAP 2.0 ATR",
            {
                "ORVWAP_MIN_VOLUME_RATIO": 1.2,
                "ORVWAP_OR_BREAKOUT_BUFFER_PCT": 0.05,
                "ORVWAP_MAX_VWAP_EXTENSION_ATR": 2.0,
            },
        ),
    ]

    print("\nScenario simulations:")
    for label, overrides in scenarios:
        original = {key: getattr(config, key) for key in overrides}
        for key, value in overrides.items():
            setattr(config, key, value)
        passes, fail_counter = simulate(df, strategy)
        for key, value in original.items():
            setattr(config, key, value)
        top_fail = fail_counter.most_common(1)[0] if fail_counter else None
        print(f"  {label:45} passes={passes:4d} top_fail={top_fail}")


if __name__ == "__main__":
    main()
