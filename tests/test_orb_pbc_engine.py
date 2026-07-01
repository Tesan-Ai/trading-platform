"""End-to-end integration test for the dedicated ORB-PBC backtest engine.

This runs the real engine against the repo's actual historical 1-minute data
(a bounded date window, for speed) so a timezone bug, a broken merge, or a
schema mismatch between features/intraday_indicators.py,
strategies/orb_pullback_continuation.py, and backtesting/orb_pbc_engine.py
would be caught even though each module's unit tests pass in isolation.

Skips gracefully (rather than failing) if the historical data files are not
present in this environment.
"""

import os

import pytest

import config
from backtesting.orb_pbc_engine import run_orb_pbc_backtest

DATA_DIR = "historical_data"
REQUIRED_FILES = ["NVDA.csv", "META.csv", "AMD.csv", "TSLA.csv", "SPY.csv", "QQQ.csv"]


def _data_available() -> bool:
    return all(os.path.exists(os.path.join(DATA_DIR, name)) for name in REQUIRED_FILES)


@pytest.mark.skipif(not _data_available(), reason="historical_data/ fixtures not present in this environment")
def test_engine_runs_end_to_end_and_produces_only_long_trades():
    result = run_orb_pbc_backtest(
        symbols=["NVDA", "META", "AMD", "TSLA"],
        market_filter_symbols=["SPY", "QQQ"],
        data_dir=DATA_DIR,
        start_date="2025-09-03",
        end_date="2026-01-22",
        starting_equity=10_000.0,
    )

    assert result.ending_equity > 0
    assert isinstance(result.trade_rows, list)
    assert isinstance(result.equity_curve, list)

    for trade in result.trade_rows:
        assert trade["ticker"] in config.ORB_PBC_SYMBOLS
        assert trade["position_size"] > 0
        assert trade["exit_timestamp"] > trade["entry_timestamp"]
        # v1.0 is long-only: every trade's exit price move direction is
        # unconstrained (can be a loss), but there must be no SHORT-style
        # bookkeeping anywhere (e.g. negative position size).
        assert trade["position_size"] > 0


@pytest.mark.skipif(not _data_available(), reason="historical_data/ fixtures not present in this environment")
def test_engine_never_exceeds_max_concurrent_positions():
    result = run_orb_pbc_backtest(
        symbols=["NVDA", "META", "AMD", "TSLA"],
        market_filter_symbols=["SPY", "QQQ"],
        data_dir=DATA_DIR,
        start_date="2025-09-03",
        end_date="2026-01-22",
        starting_equity=10_000.0,
    )

    open_intervals = [(row["entry_timestamp"], row["exit_timestamp"]) for row in result.trade_rows]
    for i, (entry_i, exit_i) in enumerate(open_intervals):
        overlapping = 1
        for j, (entry_j, exit_j) in enumerate(open_intervals):
            if i == j:
                continue
            if entry_j < exit_i and exit_j > entry_i:
                overlapping += 1
        assert overlapping <= config.ORB_PBC_MAX_CONCURRENT_POSITIONS


@pytest.mark.skipif(not _data_available(), reason="historical_data/ fixtures not present in this environment")
def test_engine_reports_missing_symbol_data_without_crashing():
    result = run_orb_pbc_backtest(
        symbols=["NVDA", "NOTASYMBOL_XYZ"],
        market_filter_symbols=["SPY", "QQQ"],
        data_dir=DATA_DIR,
        start_date="2025-09-03",
        end_date="2025-10-03",
        starting_equity=10_000.0,
    )
    assert any("NOTASYMBOL_XYZ" in note for note in result.data_notes)
