"""Label historical candidate trades for ML training.

label = 1 if target would be reached before stop on forward minute bars.
label = 0 if stop would be hit before target.
"""

from __future__ import annotations

from typing import Any

import pandas as pd


def label_candidate_from_forward_bars(
    entry_price: float,
    stop_price: float,
    target_price: float,
    forward_bars: pd.DataFrame,
    side: str = "LONG",
) -> dict[str, Any]:
    """Simulate a long trade on forward 1-minute bars.

    Uses bar high/low to detect stop/target touches (conservative: stop checked
    before target within each bar when both could occur).
    """
    if forward_bars is None or forward_bars.empty:
        return {
            "label": None,
            "realized_pnl": None,
            "r_multiple": None,
            "max_favorable_excursion": None,
            "max_adverse_excursion": None,
            "exit_reason": "no_forward_data",
        }

    entry = float(entry_price)
    stop = float(stop_price)
    target = float(target_price)
    risk = abs(entry - stop) or 1e-9

    max_favorable = 0.0
    max_adverse = 0.0
    exit_price = float(forward_bars.iloc[-1]["close"])
    exit_reason = "session_end"

    for _, bar in forward_bars.iterrows():
        high = float(bar["high"])
        low = float(bar["low"])

        if side.upper() == "LONG":
            max_favorable = max(max_favorable, high - entry)
            max_adverse = max(max_adverse, entry - low)
            stop_hit = low <= stop
            target_hit = high >= target
        else:
            max_favorable = max(max_favorable, entry - low)
            max_adverse = max(max_adverse, high - entry)
            stop_hit = high >= stop
            target_hit = low <= target

        if stop_hit:
            exit_price = stop
            exit_reason = "stop"
            label = 0
            break
        if target_hit:
            exit_price = target
            exit_reason = "target"
            label = 1
            break
    else:
        pnl = (exit_price - entry) if side.upper() == "LONG" else (entry - exit_price)
        label = 1 if pnl > 0 else 0
        exit_reason = "session_end"

    pnl = (exit_price - entry) if side.upper() == "LONG" else (entry - exit_price)
    r_multiple = pnl / risk

    return {
        "label": int(label),
        "realized_pnl": float(pnl),
        "r_multiple": float(r_multiple),
        "max_favorable_excursion": float(max_favorable),
        "max_adverse_excursion": float(max_adverse),
        "exit_reason": exit_reason,
        "exit_price": float(exit_price),
    }


def build_labeled_row(feature_row: dict, label_info: dict) -> dict:
    """Merge feature row with label columns."""
    merged = dict(feature_row)
    merged.update(
        {
            "label": label_info.get("label"),
            "realized_pnl": label_info.get("realized_pnl"),
            "r_multiple": label_info.get("r_multiple"),
            "max_favorable_excursion": label_info.get("max_favorable_excursion"),
            "max_adverse_excursion": label_info.get("max_adverse_excursion"),
            "exit_reason": label_info.get("exit_reason"),
        }
    )
    return merged
