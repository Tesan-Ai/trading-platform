from __future__ import annotations

import argparse
import json

import config
from analytics.research_lab import build_research_lab_report, save_research_lab_report
from backtesting.profitability_replay import run_profitability_replay
from database.repositories import save_research_report
from monitoring.sentry_setup import init_sentry
from strategies.factory import get_strategy


def main() -> None:
    init_sentry()
    parser = argparse.ArgumentParser(description="Run a full strategy Research Lab workflow.")
    parser.add_argument("--strategy", default=config.ACTIVE_STRATEGY)
    parser.add_argument("--start-date", default="2025-09-03")
    parser.add_argument("--end-date", default="2026-06-03")
    parser.add_argument("--symbols", nargs="+", default=None)
    parser.add_argument("--market-filters", nargs="*", default=None)
    parser.add_argument("--profile", default="conservative", choices=["conservative", "balanced", "exploratory"])
    parser.add_argument("--capital", type=float, default=float(config.INITIAL_CAPITAL))
    parser.add_argument("--data-dir", default="historical_data")
    parser.add_argument("--output-dir", default="research_results/research_lab")
    parser.add_argument("--monte-carlo-runs", type=int, default=1000)
    args = parser.parse_args()

    _configure_run(args)
    strategy = get_strategy(args.strategy)
    trade_symbols = _trade_symbols(args, strategy)
    market_filters = _market_filters(args, strategy)
    replay_symbols = list(dict.fromkeys(trade_symbols + market_filters))

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
    paths = save_research_lab_report(report, args.output_dir)
    save_research_report(report)
    _print_summary(report, paths)


def _configure_run(args) -> None:
    config.ACTIVE_STRATEGY = args.strategy
    if args.strategy == config.ORVWAP_STRATEGY_NAME:
        trade_symbols = [symbol.upper() for symbol in (args.symbols or config.ORVWAP_TRADE_SYMBOLS)]
        config.ORVWAP_TRADE_SYMBOLS = trade_symbols
        config.TRADE_SYMBOLS = trade_symbols
        if args.profile == "conservative":
            config.ORVWAP_MAX_POSITIONS = min(int(config.ORVWAP_MAX_POSITIONS), 1)
            config.ORVWAP_MAX_TRADES_PER_DAY = min(int(config.ORVWAP_MAX_TRADES_PER_DAY), 3)


def _trade_symbols(args, strategy) -> list[str]:
    if args.symbols:
        return [symbol.upper() for symbol in args.symbols]
    if getattr(strategy, "name", "") == config.ORVWAP_STRATEGY_NAME:
        return list(config.ORVWAP_TRADE_SYMBOLS)
    return list(getattr(config, "TRADE_SYMBOLS", [])) or ["AAPL", "MSFT", "NVDA", "AMD", "META", "TSLA", "AMZN"]


def _market_filters(args, strategy) -> list[str]:
    if args.market_filters is not None:
        return [symbol.upper() for symbol in args.market_filters]
    if getattr(strategy, "name", "") == config.ORVWAP_STRATEGY_NAME:
        return [config.ORVWAP_MARKET_FILTER_SYMBOL, config.ORVWAP_TECH_FILTER_SYMBOL]
    return [getattr(config, "MARKET_REGIME_SYMBOL", "QQQ")]


def _print_summary(report: dict, paths: dict) -> None:
    backtest = report["backtest"]
    gate = report["validation_gate"]
    mc = report["monte_carlo"]
    print("\nRESEARCH LAB SUMMARY")
    print("====================")
    print(f"Strategy:          {report['strategy_name']}")
    print(f"Status:            {report['status']}")
    print(f"Recommendation:    {report['promotion_recommendation']['recommendation']}")
    print(f"Closed trades:     {backtest.get('closed_trades')}")
    print(f"Total return:      {_pct(backtest.get('total_return'))}")
    print(f"Profit factor:     {backtest.get('profit_factor')}")
    print(f"Expectancy:        ${float(backtest.get('expectancy', 0.0) or 0.0):.2f}")
    print(f"Max drawdown:      {_pct(backtest.get('max_drawdown'))}")
    print(f"MC loss prob:      {_pct(mc.get('probability_of_loss'))}")
    print(f"Gate passes:       {gate.get('passes')}")
    for reason in gate.get("reasons", []):
        print(f"- {reason}")
    print("\nReports saved:")
    print(json.dumps(paths, indent=2))


def _pct(value) -> str:
    if value is None:
        return "not available"
    return f"{float(value) * 100:.2f}%"


if __name__ == "__main__":
    main()
