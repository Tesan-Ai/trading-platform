"""Tests for the daily universe scanner."""

from __future__ import annotations

from datetime import date

import pandas as pd

from strategies.universe_scanner import (
    ScannerConfig,
    build_daily_selections,
    compute_symbol_scan_frame,
)


def _synthetic_minute(symbol: str, session_date: date, or_volume: float) -> pd.DataFrame:
    base = pd.Timestamp(f"{session_date.isoformat()} 09:30:00", tz="America/New_York")
    rows = []
    for minute in range(5):
        rows.append(
            {
                "timestamp": base + pd.Timedelta(minutes=minute),
                "open": 100.0,
                "high": 101.0,
                "low": 99.0,
                "close": 100.0 + minute,
                "volume": or_volume / 5.0,
            }
        )
    for minute in range(5, 30):
        rows.append(
            {
                "timestamp": base + pd.Timedelta(minutes=minute),
                "open": 105.0,
                "high": 106.0,
                "low": 104.0,
                "close": 105.0,
                "volume": 1000.0,
            }
        )
    return pd.DataFrame(rows)


def test_high_opening_rvol_symbol_ranks_above_quiet_symbol():
    cfg = ScannerConfig(top_n=1, min_opening_rvol=1.0, rvol_lookback_days=3, min_atr_d_pct=0.0)
    days = [date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4), date(2024, 1, 5), date(2024, 1, 8)]

    loud = pd.concat([_synthetic_minute("LOUD", day, 50000.0) for day in days[:-1]], ignore_index=True)
    loud = pd.concat([loud, _synthetic_minute("LOUD", days[-1], 500000.0)], ignore_index=True)
    quiet = pd.concat([_synthetic_minute("QUIET", day, 50000.0) for day in days], ignore_index=True)

    selections = build_daily_selections({"LOUD": loud, "QUIET": quiet}, cfg)
    assert days[-1] in selections
    assert selections[days[-1]][0] == "LOUD"


def test_compute_symbol_scan_frame_has_opening_rvol():
    cfg = ScannerConfig(rvol_lookback_days=2, min_atr_d_pct=0.0)
    day = date(2024, 2, 1)
    frame = compute_symbol_scan_frame("TEST", _synthetic_minute("TEST", day, 10000.0), cfg)
    assert not frame.empty
    assert "opening_rvol" in frame.columns
