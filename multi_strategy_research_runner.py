from __future__ import annotations

import argparse
import json
import traceback

import config
from analytics.multi_strategy import build_multi_strategy_report, save_multi_strategy_report
from analytics.research_lab import build_research_lab_report, save_research_lab_report
from backtesting.profitability_replay import run_profitability_replay
from monitoring.sentry_setup import init_sentry
from strategies.factory import STRATEGY_REGISTRY, get_strategy


DEFAULT_STRATEGIES = [
    config.ORVWAP_STRATEGY_NAME,
    "momentum_breakout_v1",
    "bull_day_trade_v1",
    "daily_trend_v1",
]


def main() -> None:
    init_sentry()
    parser = argparse.ArgumentParser(description="Run research-only comparison across multiple strategies.")
    parser.add_argument("--strategies", nargs="+", default=DEFAULT_STRATEGIES)
    parser.add_argument("--start-date", default="2025-09-03")
    parser.add_argument("--end-date", default="2026-06-03")
    parser.add_argument("--symbols", nargs="+", default=None)
    parser.add_argument("--profile", default="conservative", choices=["conservative", "balanced", "exploratory"])
    parser.add_argument("--capital", type=float, default=float(config.INITIAL_CAPITAL))
    parser.add_argument("--data-dir", default="historical_data")
    parser.add_argument("--output-dir", default="research_results/multi_strategy")
    parser.add_argument("--single-report-dir", default="research_results/research_lab")
    parser.add_argument("--monte-carlo-runs", type=int, default=300)
    args = parser.parse_args()

    reports = []
    skipped = []
    symbols_by_strategy = {}
    market_filters_by_strategy = {}
    original_active_strategy = config.ACTIVE_STRATEGY
    original_trade_symbols = list(getattr(config, "TRADE_SYMBOLS", []))

    for strategy_name in _unique(args.strategies):
        if strategy_name not in STRATEGY_REGISTRY:
            skipped.append({"strategy_name": strategy_name, "reason": "unknown strategy"})
            continue

        try:
            strategy = get_strategy(strategy_name)
            if not _is_runnable_strategy(strategy):
                skipped.append({"strategy_name": strategy_name, "reason": "strategy does not implement evaluate_entry/evaluate_exit"})
                continue

            _configure_strategy_run(args, strategy)
            trade_symbols = _trade_symbols(args, strategy)
            market_filters = _market_filters(strategy)
            replay_symbols = _unique(trade_symbols + market_filters)
            symbols_by_strategy[strategy.name] = trade_symbols
            market_filters_by_strategy[strategy.name] = market_filters

            result = run_profitability_replay(
                symbols=replay_symbols,
                data_dir=args.data_dir,
                starting_cash=args.capital,
                start_date=args.start_date,
                end_date=args.end_date,
                strategy=strategy,
            )
            trade_rows = result.get("trade_rows", [])
            equity_curve = result.get("portfolio").equity_curve if result.get("portfolio") else []
            report = build_research_lab_report(
                strategy_name=strategy.name,
                profile=args.profile,
                start_date=args.start_date,
                end_date=args.end_date,
                symbols=trade_symbols,
                market_filters=market_filters,
                starting_equity=args.capital,
                trade_rows=trade_rows,
                equity_curve=equity_curve,
                base_report=result.get("report", {}),
                monte_carlo_runs=args.monte_carlo_runs,
            )
            paths = save_research_lab_report(report, args.single_report_dir)
            report["_report_path"] = paths["json_path"]
            reports.append(report)
            _print_strategy_summary(report)
        except Exception as exc:  # noqa: BLE001
            skipped.append(
                {
                    "strategy_name": strategy_name,
                    "reason": str(exc),
                    "traceback": traceback.format_exc(limit=8),
                }
            )
            print(f"SKIP {strategy_name}: {exc}")

    config.ACTIVE_STRATEGY = original_active_strategy
    config.TRADE_SYMBOLS = original_trade_symbols

    multi_report = build_multi_strategy_report(
        reports=reports,
        skipped=skipped,
        start_date=args.start_date,
        end_date=args.end_date,
        profile=args.profile,
        symbols_by_strategy=symbols_by_strategy,
        market_filters_by_strategy=market_filters_by_strategy,
    )
    paths = save_multi_strategy_report(multi_report, args.output_dir)
    _print_multi_summary(multi_report, paths)


def _configure_strategy_run(args, strategy) -> None:
    config.ACTIVE_STRATEGY = strategy.name
    if strategy.name == config.ORVWAP_STRATEGY_NAME:
        trade_symbols = [symbol.upper() for symbol in (args.symbols or config.ORVWAP_TRADE_SYMBOLS)]
        config.ORVWAP_TRADE_SYMBOLS = trade_symbols
        config.TRADE_SYMBOLS = trade_symbols
        if args.profile == "conservative":
            config.ORVWAP_MAX_POSITIONS = min(int(config.ORVWAP_MAX_POSITIONS), 1)
            config.ORVWAP_MAX_TRADES_PER_DAY = min(int(config.ORVWAP_MAX_TRADES_PER_DAY), 3)
    else:
        config.TRADE_SYMBOLS = [symbol.upper() for symbol in (args.symbols or _default_non_orvwap_symbols())]


def _trade_symbols(args, strategy) -> list[str]:
    if args.symbols:
        return [symbol.upper() for symbol in args.symbols]
    if strategy.name == config.ORVWAP_STRATEGY_NAME:
        return list(config.ORVWAP_TRADE_SYMBOLS)
    return _default_non_orvwap_symbols()


def _market_filters(strategy) -> list[str]:
    if strategy.name == config.ORVWAP_STRATEGY_NAME:
        return [config.ORVWAP_MARKET_FILTER_SYMBOL, config.ORVWAP_TECH_FILTER_SYMBOL]
    return [getattr(config, "MARKET_REGIME_SYMBOL", "QQQ")]


def _default_non_orvwap_symbols() -> list[str]:
    return list(getattr(config, "ORVWAP_TRADE_SYMBOLS", [])) or ["AAPL", "MSFT", "NVDA", "AMD", "META", "TSLA", "AMZN"]


def _is_runnable_strategy(strategy) -> bool:
    return callable(getattr(strategy, "evaluate_entry", None)) and callable(getattr(strategy, "evaluate_exit", None))


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _print_strategy_summary(report: dict) -> None:
    backtest = report["backtest"]
    print(
        f"{report['strategy_name']}: trades={backtest.get('closed_trades')} "
        f"return={_pct(backtest.get('total_return'))} "
        f"pf={backtest.get('profit_factor')} "
        f"expectancy=${float(backtest.get('expectancy', 0.0) or 0.0):.2f}"
    )


def _print_multi_summary(report: dict, paths: dict) -> None:
    print("\nMULTI-STRATEGY RESEARCH SUMMARY")
    print("===============================")
    print(f"Mode:              {report['mode']}")
    print(f"Strategies tested: {report['summary']['strategies_tested']}")
    print(f"Strategies skipped:{report['summary']['strategies_skipped']}")
    print(f"Top strategy:      {report['summary']['top_strategy']}")
    print(f"Allocator mode:    {report['strategy_allocator']['mode']}")
    print(f"Reason:            {report['strategy_allocator']['reason']}")
    print("\nLeaderboard:")
    for row in report.get("leaderboard", []):
        print(
            f"{row['rank']}. {row['strategy_name']} "
            f"score={row['score']} trades={row['closed_trades']} "
            f"pf={row['profit_factor']} exp={row['expectancy']}"
        )
    print("\nReports saved:")
    print(json.dumps(paths, indent=2))


def _pct(value) -> str:
    if value is None:
        return "not available"
    return f"{float(value) * 100:.2f}%"


if __name__ == "__main__":
    main()
