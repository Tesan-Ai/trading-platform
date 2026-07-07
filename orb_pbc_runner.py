"""CLI entry point for ORB-PBC v1.0 research backtests.

RESEARCH ONLY. This script never enables live trading, never changes
``config.TRADING_MODE``, and never bypasses ``risk/risk_gate.py``. It runs
the dedicated ORB-PBC backtest engine (``backtesting/orb_pbc_engine.py``)
three times per invocation (after-costs baseline, before-costs, and a 2x
slippage stress test), optionally runs a walk-forward pass, and writes a
JSON + Markdown report plus a CSV summary row under
``research_results/orb_pbc_v1/``.

Example:

    python orb_pbc_runner.py \\
        --strategy orb_pullback_continuation_v1 \\
        --start-date 2025-09-03 \\
        --end-date 2026-06-03 \\
        --symbols NVDA META AMD TSLA \\
        --market-filters SPY QQQ \\
        --profile baseline \\
        --monte-carlo-runs 1000 \\
        --include-costs \\
        --slippage-stress 2.0
"""

from __future__ import annotations

import argparse
import json

import config
from analytics.orb_pbc_report import build_orb_pbc_report, save_orb_pbc_report
from backtesting.orb_pbc_engine import run_orb_pbc_backtest
from orb_pbc_walk_forward import run_orb_pbc_walk_forward


def main() -> None:
    parser = argparse.ArgumentParser(description="Run an ORB-PBC v1.0 research backtest (RESEARCH ONLY).")
    parser.add_argument("--strategy", default=config.ORB_PBC_STRATEGY_NAME)
    parser.add_argument("--start-date", default="2025-09-03")
    parser.add_argument("--end-date", default="2026-06-03")
    parser.add_argument("--symbols", nargs="+", default=list(config.ORB_PBC_SYMBOLS))
    parser.add_argument("--market-filters", nargs="+", default=list(config.ORB_PBC_MARKET_FILTER_SYMBOLS))
    parser.add_argument("--timeframe", default="5min", help="Informational only; always 5min bars built from 1min data.")
    parser.add_argument("--profile", default="baseline", choices=["baseline", "all_symbols_filter_driven"])
    parser.add_argument("--capital", type=float, default=float(config.ORB_PBC_EQUITY))
    parser.add_argument("--data-dir", default="historical_data")
    parser.add_argument("--output-dir", default="research_results/orb_pbc_v1")
    parser.add_argument("--monte-carlo-runs", type=int, default=1000)
    parser.add_argument("--include-costs", action="store_true", default=True)
    parser.add_argument("--slippage-stress", type=float, default=float(config.ORB_PBC_SLIPPAGE_STRESS_MULTIPLIER))
    parser.add_argument("--walk-forward", action="store_true", help="Also run a walk-forward pass and include it in the report.")
    parser.add_argument(
        "--universe",
        choices=["fixed", "scanner"],
        default="fixed",
        help="fixed = configured symbol list; scanner = daily 'stocks in play' selection",
    )
    parser.add_argument("--scanner-top-n", type=int, default=None)
    parser.add_argument("--train-months", type=int, default=6)
    parser.add_argument("--test-months", type=int, default=3)
    args = parser.parse_args()

    if args.strategy != config.ORB_PBC_STRATEGY_NAME:
        raise SystemExit(
            f"orb_pbc_runner.py only supports {config.ORB_PBC_STRATEGY_NAME}; got --strategy {args.strategy}"
        )

    symbols = [symbol.upper() for symbol in args.symbols]
    if args.profile == "all_symbols_filter_driven":
        symbols = [symbol.upper() for symbol in (config.ORB_PBC_SYMBOLS + config.ORB_PBC_OPTIONAL_SYMBOLS)]
    market_filters = [symbol.upper() for symbol in args.market_filters]
    daily_allowed_symbols = None

    if args.universe == "scanner":
        from strategies.universe_scanner import (
            ScannerConfig,
            build_scanner_backtest_context,
            save_daily_selections,
            scanner_config_from_env,
        )

        scanner_cfg = scanner_config_from_env()
        if args.scanner_top_n is not None:
            scanner_cfg = ScannerConfig(
                top_n=args.scanner_top_n,
                min_price=scanner_cfg.min_price,
                min_opening_rvol=scanner_cfg.min_opening_rvol,
                opening_range_minutes=scanner_cfg.opening_range_minutes,
                rvol_lookback_days=scanner_cfg.rvol_lookback_days,
                min_atr_d_pct=scanner_cfg.min_atr_d_pct,
            )
        scanner_meta = build_scanner_backtest_context(
            data_dir=args.data_dir,
            start_date=args.start_date,
            end_date=args.end_date,
            cfg=scanner_cfg,
            market_filter_symbols=market_filters,
        )
        symbols = scanner_meta["loaded_symbols"]
        daily_allowed_symbols = scanner_meta["daily_selections"]
        save_daily_selections(
            daily_allowed_symbols,
            getattr(config, "SCANNER_SELECTION_LOG_DIR", "research_results/scanner"),
            f"orb_pbc_{args.profile}",
        )
        print(
            f"Scanner mode: {scanner_meta['selection_days']} selection days, "
            f"{scanner_meta['avg_symbols_per_day']:.1f} symbols/day avg "
            f"from {len(symbols)} loaded symbols."
        )

    print(f"Running ORB-PBC v1.0 baseline (after costs) for {len(symbols)} symbols from {args.start_date} to {args.end_date} ...")
    result_after_costs = run_orb_pbc_backtest(
        symbols=symbols,
        market_filter_symbols=market_filters,
        data_dir=args.data_dir,
        start_date=args.start_date,
        end_date=args.end_date,
        starting_equity=args.capital,
        include_costs=True,
        slippage_multiplier=1.0,
        daily_allowed_symbols=daily_allowed_symbols,
    )
    print(f"  -> {len(result_after_costs.trade_rows)} closed trades.")

    print("Running before-costs comparison pass ...")
    result_before_costs = run_orb_pbc_backtest(
        symbols=symbols,
        market_filter_symbols=market_filters,
        data_dir=args.data_dir,
        start_date=args.start_date,
        end_date=args.end_date,
        starting_equity=args.capital,
        include_costs=False,
        slippage_multiplier=0.0,
        daily_allowed_symbols=daily_allowed_symbols,
    )
    print(f"  -> {len(result_before_costs.trade_rows)} closed trades.")

    print(f"Running {args.slippage_stress}x slippage stress pass ...")
    result_slippage_stress = run_orb_pbc_backtest(
        symbols=symbols,
        market_filter_symbols=market_filters,
        data_dir=args.data_dir,
        start_date=args.start_date,
        end_date=args.end_date,
        starting_equity=args.capital,
        include_costs=True,
        slippage_multiplier=args.slippage_stress,
        daily_allowed_symbols=daily_allowed_symbols,
    )
    print(f"  -> {len(result_slippage_stress.trade_rows)} closed trades.")

    walk_forward = None
    if args.walk_forward:
        if args.universe == "scanner":
            print("Skipping walk-forward in scanner mode (not yet supported with daily selections).")
        else:
            print("Running walk-forward validation pass ...")
            walk_forward = run_orb_pbc_walk_forward(
                symbols=symbols,
                market_filter_symbols=market_filters,
                start_date=args.start_date,
                end_date=args.end_date,
                train_months=args.train_months,
                test_months=args.test_months,
                data_dir=args.data_dir,
                starting_equity=args.capital,
            )

    report = build_orb_pbc_report(
        profile=args.profile,
        start_date=args.start_date,
        end_date=args.end_date,
        symbols=symbols,
        market_filters=market_filters,
        starting_equity=args.capital,
        result_after_costs=result_after_costs,
        result_before_costs=result_before_costs,
        result_slippage_stress=result_slippage_stress,
        walk_forward=walk_forward,
        monte_carlo_runs=args.monte_carlo_runs,
    )
    paths = save_orb_pbc_report(report, args.output_dir)
    _print_summary(report, paths)


def _print_summary(report: dict, paths: dict) -> None:
    backtest = report["backtest_after_costs"]
    gate = report["validation_gate_orb_pbc"]
    mc = report["monte_carlo"]
    print("\nORB-PBC v1.0 RESEARCH SUMMARY")
    print("=============================")
    print(f"Strategy:          {report['strategy_name']}")
    print(f"Status:            {report['status']}")
    print(f"Recommendation:    {report['recommendation']['recommendation']}")
    print(f"Closed trades:     {backtest.get('closed_trades')}")
    print(f"Trades/year (est): {gate.get('trades_per_year')}")
    print(f"Total return:      {_pct(backtest.get('total_return'))}")
    print(f"Profit factor:     {backtest.get('profit_factor')}")
    print(f"Avg R multiple:    {gate.get('avg_r_multiple')}")
    print(f"Expectancy:        ${float(backtest.get('expectancy', 0.0) or 0.0):.2f}")
    print(f"Max drawdown:      {_pct(backtest.get('max_drawdown'))}")
    print(f"MC P(negative):    {_pct(mc.get('probability_of_loss'))}")
    print(f"Gate passes:       {gate.get('passes')}")
    if gate.get("reject_reasons_triggered"):
        print("Reject reasons:")
        for reason in gate["reject_reasons_triggered"]:
            print(f"  - {reason}")
    print("\nReports saved:")
    print(json.dumps(paths, indent=2))


def _pct(value) -> str:
    if value is None:
        return "not available"
    return f"{float(value) * 100:.2f}%"


if __name__ == "__main__":
    main()
