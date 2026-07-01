import argparse
from datetime import date

import pandas as pd

import config
from analytics.trade_analytics import calculate_report, print_report
from analytics.strategy_scorecard import build_strategy_scorecard, print_strategy_scorecard
from backtesting.profitability_replay import run_profitability_replay
from experiments.tracker import record_experiment
from monitoring.sentry_setup import init_sentry
from strategies.factory import get_strategy
from validation.performance_gate import evaluate_validation_gate, print_validation_gate


def main() -> None:
    init_sentry()
    parser = argparse.ArgumentParser(description="Run walk-forward strategy validation.")
    parser.add_argument("--strategy", default=config.ACTIVE_STRATEGY)
    parser.add_argument("--start-date", default="2025-09-03")
    parser.add_argument("--end-date", default="2026-06-03")
    parser.add_argument("--fold-months", type=int, default=1)
    parser.add_argument("--capital", type=float, default=float(config.INITIAL_CAPITAL))
    parser.add_argument("--data-dir", default="historical_data")
    parser.add_argument("--output-dir", default="research_results/experiments")
    parser.add_argument("--orvwap-relaxed", action="store_true")
    parser.add_argument(
        "--orvwap-quality-profile",
        action="store_true",
        help="Use the current research candidate: relaxed filters, MSFT/META only.",
    )
    parser.add_argument("--exclude-symbol", action="append", default=[])
    parser.add_argument("--block-entry-hour-et", type=int, action="append", default=[])
    args = parser.parse_args()

    _configure_strategy(args)
    strategy = get_strategy(args.strategy)
    symbols = _symbols_for_strategy(strategy)
    folds = build_walk_forward_folds(args.start_date, args.end_date, args.fold_months)

    all_trade_rows = []
    fold_reports = []
    for fold_start, fold_end in folds:
        result = run_profitability_replay(
            symbols=symbols,
            data_dir=args.data_dir,
            starting_cash=args.capital,
            start_date=fold_start.isoformat(),
            end_date=fold_end.isoformat(),
            strategy=strategy,
        )
        report = dict(result["report"])
        report["start_date"] = fold_start.isoformat()
        report["end_date"] = fold_end.isoformat()
        report["total_pnl"] = sum(float(row["pnl_dollars"]) for row in result["trade_rows"])
        fold_reports.append(report)
        all_trade_rows.extend(result["trade_rows"])

        print(
            f"Fold {fold_start} -> {fold_end}: "
            f"trades={report.get('closed_trades', 0)} "
            f"pf={float(report.get('profit_factor', 0.0) or 0.0):.2f} "
            f"exp=${float(report.get('expectancy', 0.0) or 0.0):.2f}"
        )

    aggregate_report = calculate_report(all_trade_rows, [])
    aggregate_report["folds"] = fold_reports
    aggregate_report["total_pnl"] = sum(float(row["pnl_dollars"]) for row in all_trade_rows)
    aggregate_report["profitable_folds"] = sum(
        1 for report in fold_reports if float(report.get("expectancy", 0.0) or 0.0) > 0
    )
    aggregate_report["total_folds"] = len(fold_reports)

    gate = evaluate_validation_gate(aggregate_report, stage="backtest")
    scorecard = build_strategy_scorecard(all_trade_rows)
    aggregate_report["scorecard"] = scorecard
    parameters = {
        "start_date": args.start_date,
        "end_date": args.end_date,
        "fold_months": args.fold_months,
        "symbols": symbols,
        "orvwap_relaxed": args.orvwap_relaxed,
        "orvwap_quality_profile": args.orvwap_quality_profile,
        "excluded_symbols": sorted(getattr(config, "ORVWAP_EXCLUDED_SYMBOLS", set())),
        "blocked_entry_hours_et": sorted(getattr(config, "ORVWAP_BLOCKED_ENTRY_HOURS_ET", set())),
    }
    experiment_path = record_experiment(
        strategy.name,
        aggregate_report,
        gate,
        parameters=parameters,
        output_dir=args.output_dir,
    )

    print("\nWalk-forward aggregate")
    print("======================")
    print(f"Strategy:             {strategy.name}")
    print(f"Symbols:              {', '.join(symbols)}")
    print(f"Folds:                {len(folds)}")
    print(f"Profitable folds:     {aggregate_report['profitable_folds']}/{aggregate_report['total_folds']}")
    print_report(aggregate_report)
    print_strategy_scorecard(scorecard)
    print_validation_gate(gate)
    print(f"\nExperiment saved to: {experiment_path}")


def build_walk_forward_folds(start_date: str, end_date: str, fold_months: int) -> list[tuple[date, date]]:
    start = pd.Timestamp(start_date).date()
    end = pd.Timestamp(end_date).date()
    if fold_months < 1:
        raise ValueError("fold-months must be at least 1")

    folds = []
    fold_start = pd.Timestamp(start)
    final = pd.Timestamp(end)
    while fold_start <= final:
        fold_end = min(fold_start + pd.DateOffset(months=fold_months) - pd.DateOffset(days=1), final)
        folds.append((fold_start.date(), fold_end.date()))
        fold_start = fold_end + pd.DateOffset(days=1)
    return folds


def _configure_strategy(args) -> None:
    config.ACTIVE_STRATEGY = args.strategy
    if args.strategy == config.ORVWAP_STRATEGY_NAME:
        if args.orvwap_relaxed or args.orvwap_quality_profile:
            config.ORVWAP_MIN_VOLUME_RATIO = 1.2
            config.ORVWAP_OR_BREAKOUT_BUFFER_PCT = 0.05
            config.ORVWAP_MAX_VWAP_EXTENSION_ATR = 2.0
        if args.orvwap_quality_profile:
            config.ORVWAP_EXCLUDED_SYMBOLS = {"NVDA", "TSLA", "AAPL", "AMZN", "AMD"}
        if args.exclude_symbol:
            config.ORVWAP_EXCLUDED_SYMBOLS = {
                symbol.strip().upper() for symbol in args.exclude_symbol if symbol.strip()
            }
        if args.block_entry_hour_et:
            config.ORVWAP_BLOCKED_ENTRY_HOURS_ET = set(args.block_entry_hour_et)
        config.TRADE_SYMBOLS = list(getattr(config, "ORVWAP_TRADE_SYMBOLS", config.ORVWAP_UNIVERSE))


def _symbols_for_strategy(strategy) -> list[str]:
    if getattr(strategy, "name", "") == config.ORVWAP_STRATEGY_NAME:
        return list(
            dict.fromkeys(
                list(getattr(config, "ORVWAP_TRADE_SYMBOLS", config.ORVWAP_UNIVERSE))
                + [config.ORVWAP_MARKET_FILTER_SYMBOL, config.ORVWAP_TECH_FILTER_SYMBOL]
            )
        )
    configured = list(getattr(config, "TRADE_SYMBOLS", []))
    return configured or ["AAPL", "MSFT", "NVDA", "AMD", "META", "TSLA", "AMZN", "QQQ", "SPY"]


if __name__ == "__main__":
    main()
