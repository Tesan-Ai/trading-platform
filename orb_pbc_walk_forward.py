"""Walk-forward validation for ORB-PBC v1.0.

RESEARCH ONLY. Reuses ``walk_forward_runner.build_walk_forward_folds`` for
fold construction and ``backtesting/orb_pbc_engine.run_orb_pbc_backtest`` for
each fold's in-sample (train) and out-of-sample (test) backtest.

No parameter optimization happens here (per the spec's "do not optimize
first" instruction) -- every fold runs the same baseline ORB-PBC config on
its train and test windows, and Walk-Forward Efficiency is reported as
OOS average R / IS average R.
"""

from __future__ import annotations

import argparse

import config
from backtesting.orb_pbc_engine import run_orb_pbc_backtest
from validation.orb_pbc_gate import compute_avg_r_multiple


def run_orb_pbc_walk_forward(
    symbols: list[str],
    market_filter_symbols: list[str] = None,
    start_date: str = "2025-09-03",
    end_date: str = "2026-06-03",
    train_months: int = 6,
    test_months: int = 3,
    data_dir: str = "historical_data",
    starting_equity: float = None,
) -> dict:
    market_filter_symbols = market_filter_symbols or list(config.ORB_PBC_MARKET_FILTER_SYMBOLS)
    starting_equity = starting_equity if starting_equity is not None else config.ORB_PBC_EQUITY

    windows = _build_train_test_windows(start_date, end_date, train_months, test_months)
    if not windows:
        return {
            "folds_run": 0,
            "walk_forward_efficiency": None,
            "oos_profitable_window_pct": None,
            "fold_details": [],
            "notes": (
                f"Not available: the requested window ({start_date} to {end_date}) is too short "
                f"for even one {train_months}-month train / {test_months}-month test fold given "
                "the data actually on disk. Do not fabricate additional folds."
            ),
        }

    fold_details = []
    is_r_values = []
    oos_r_values = []
    oos_profitable_windows = 0

    for train_start, train_end, test_start, test_end in windows:
        is_result = run_orb_pbc_backtest(
            symbols=symbols,
            market_filter_symbols=market_filter_symbols,
            data_dir=data_dir,
            start_date=train_start.isoformat(),
            end_date=train_end.isoformat(),
            starting_equity=starting_equity,
        )
        oos_result = run_orb_pbc_backtest(
            symbols=symbols,
            market_filter_symbols=market_filter_symbols,
            data_dir=data_dir,
            start_date=test_start.isoformat(),
            end_date=test_end.isoformat(),
            starting_equity=starting_equity,
        )

        is_avg_r = compute_avg_r_multiple(is_result.trade_rows)
        oos_avg_r = compute_avg_r_multiple(oos_result.trade_rows)
        oos_total_pnl = sum(row["pnl_dollars"] for row in oos_result.trade_rows)

        if is_avg_r is not None:
            is_r_values.append(is_avg_r)
        if oos_avg_r is not None:
            oos_r_values.append(oos_avg_r)
        if oos_result.trade_rows:
            oos_profitable_windows += 1 if oos_total_pnl > 0 else 0

        fold_details.append(
            {
                "train_start": train_start.isoformat(),
                "train_end": train_end.isoformat(),
                "test_start": test_start.isoformat(),
                "test_end": test_end.isoformat(),
                "is_trades": len(is_result.trade_rows),
                "oos_trades": len(oos_result.trade_rows),
                "is_avg_r": is_avg_r,
                "oos_avg_r": oos_avg_r,
                "oos_total_pnl": oos_total_pnl,
            }
        )

    total_oos_windows_with_trades = sum(1 for fold in fold_details if fold["oos_trades"] > 0)
    oos_profitable_pct = (
        oos_profitable_windows / total_oos_windows_with_trades if total_oos_windows_with_trades else None
    )

    wfe = None
    if is_r_values and oos_r_values:
        avg_is = sum(is_r_values) / len(is_r_values)
        avg_oos = sum(oos_r_values) / len(oos_r_values)
        if avg_is not in (0, None):
            wfe = avg_oos / avg_is

    notes = None
    if len(windows) < 2:
        notes = (
            "Only one train/test fold fit inside the available ~9-month data window. "
            "Walk-forward efficiency from a single fold is not statistically meaningful; "
            "treat this as directional, not conclusive, evidence."
        )

    return {
        "folds_run": len(windows),
        "walk_forward_efficiency": wfe,
        "oos_profitable_window_pct": oos_profitable_pct,
        "fold_details": fold_details,
        "notes": notes or "ok",
    }


def _build_train_test_windows(start_date: str, end_date: str, train_months: int, test_months: int):
    import pandas as pd

    start = pd.Timestamp(start_date)
    end = pd.Timestamp(end_date)
    windows = []
    train_start = start
    while True:
        train_end = train_start + pd.DateOffset(months=train_months) - pd.DateOffset(days=1)
        test_start = train_end + pd.DateOffset(days=1)
        test_end = min(test_start + pd.DateOffset(months=test_months) - pd.DateOffset(days=1), end)
        if test_start > end:
            break
        windows.append((train_start.date(), train_end.date(), test_start.date(), test_end.date()))
        train_start = train_start + pd.DateOffset(months=test_months)
        if train_start >= end:
            break
    return windows


def main() -> None:
    parser = argparse.ArgumentParser(description="Walk-forward validation for ORB-PBC v1.0 (research only).")
    parser.add_argument("--strategy", default=config.ORB_PBC_STRATEGY_NAME)
    parser.add_argument("--start-date", default="2025-09-03")
    parser.add_argument("--end-date", default="2026-06-03")
    parser.add_argument("--train-months", type=int, default=6)
    parser.add_argument("--test-months", type=int, default=3)
    parser.add_argument("--symbols", nargs="+", default=list(config.ORB_PBC_SYMBOLS))
    parser.add_argument("--market-filters", nargs="+", default=list(config.ORB_PBC_MARKET_FILTER_SYMBOLS))
    parser.add_argument("--data-dir", default="historical_data")
    parser.add_argument("--capital", type=float, default=float(config.ORB_PBC_EQUITY))
    args = parser.parse_args()

    result = run_orb_pbc_walk_forward(
        symbols=[s.upper() for s in args.symbols],
        market_filter_symbols=[s.upper() for s in args.market_filters],
        start_date=args.start_date,
        end_date=args.end_date,
        train_months=args.train_months,
        test_months=args.test_months,
        data_dir=args.data_dir,
        starting_equity=args.capital,
    )

    print("\nORB-PBC WALK-FORWARD SUMMARY")
    print("============================")
    print(f"Folds run:                  {result['folds_run']}")
    print(f"Walk-forward efficiency:    {result['walk_forward_efficiency']}")
    print(f"OOS profitable window pct:  {result['oos_profitable_window_pct']}")
    print(f"Notes:                      {result['notes']}")
    for fold in result["fold_details"]:
        print(
            f"  train {fold['train_start']}..{fold['train_end']} "
            f"(trades={fold['is_trades']}, avgR={fold['is_avg_r']})  ->  "
            f"test {fold['test_start']}..{fold['test_end']} "
            f"(trades={fold['oos_trades']}, avgR={fold['oos_avg_r']}, pnl={fold['oos_total_pnl']})"
        )


if __name__ == "__main__":
    main()
