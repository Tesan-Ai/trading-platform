import argparse
import itertools
import os
from datetime import datetime

import pandas as pd

from analytics.setup_journal import (
    JOURNAL_COLUMNS,
    SUMMARY_COLUMNS,
    build_setup_journal,
    summarize_by_run,
    summarize_setup_journal,
)
from backtesting.profitability_replay import run_profitability_replay
from download_historical_data import DEFAULT_MARKET_SYMBOLS, parse_symbols
from historical_data import fetch_and_save_bars
from research_utils import temporary_config
from watchlist import ETF_RESEARCH_UNIVERSE, LEGACY_WATCHLIST, WATCHLIST


DEFAULT_CORE_SYMBOLS = [
    "AAPL", "MSFT", "NVDA", "AMD", "META",
    "TSLA", "AMZN", "PLTR", "SOFI", "RKLB"
]


def parse_csv_floats(value):
    return [float(item) for item in value.split(",") if item.strip()]


def parse_csv_ints(value):
    return [int(item) for item in value.split(",") if item.strip()]


def parse_csv_strings(value):
    return [item.strip() for item in value.split(",") if item.strip()]


def parse_csv_bools(value):
    items = []
    for item in value.split(","):
        normalized = item.strip().lower()
        if not normalized:
            continue
        items.append(normalized in {"1", "true", "yes", "y"})
    return items


def build_grid(args):
    keys = [
        "BUY_START_TIME",
        "BUY_END_TIME",
        "RSI_MIN",
        "RSI_MAX",
        "MOMENTUM_RVOL_MIN",
        "REQUIRE_BREAKOUT",
        "ATR_STOP_MULTIPLE",
        "ATR_EXTREME_PERCENT",
        "MAX_HOLD_MINUTES",
        "MAX_CAPITAL_PER_TRADE",
        "MAX_POSITIONS"
    ]
    values = [
        parse_csv_strings(args.buy_start_times),
        parse_csv_strings(args.buy_end_times),
        parse_csv_floats(args.rsi_mins),
        parse_csv_floats(args.rsi_maxes),
        parse_csv_floats(args.rvol_mins),
        parse_csv_bools(args.require_breakout),
        parse_csv_floats(args.atr_stop_multiples),
        parse_csv_floats(args.atr_extreme_percents),
        parse_csv_ints(args.max_hold_minutes),
        parse_csv_floats(args.max_capital_per_trade),
        parse_csv_ints(args.max_positions)
    ]

    for combination in itertools.product(*values):
        yield dict(zip(keys, combination))


def score_result(row):
    closed_trades = float(row["closed_trades"])
    profit_factor = float(row["profit_factor"])
    expectancy = float(row["expectancy"])
    max_drawdown = float(row["max_drawdown"])

    if closed_trades <= 0:
        return -999999.0

    if expectancy <= 0 or profit_factor <= 1:
        return (
            expectancy
            - (max_drawdown * 1000.0)
            + min(closed_trades, 100) * 0.01
        )

    return (
        expectancy
        + (profit_factor * 10.0)
        - (max_drawdown * 1000.0)
        + min(closed_trades, 100) * 0.05
    )


def run_grid(args, symbols):
    rows = []
    journal_rows = []
    grid = list(build_grid(args))

    if args.max_configs > 0:
        grid = grid[:args.max_configs]

    print(f"Research configs to run: {len(grid)}", flush=True)

    for index, overrides in enumerate(grid, start=1):
        print(f"[{index}/{len(grid)}] {overrides}", flush=True)

        research_overrides = {
            **overrides,
            "DO_NOT_TRADE_BELOW_EQUITY": args.pdt_floor
        }

        with temporary_config(research_overrides):
            result = run_profitability_replay(
                symbols=symbols,
                data_dir=args.data_dir,
                starting_cash=args.capital,
                start_date=args.start_date,
                end_date=args.end_date,
            )

        report = result["report"]
        row = {
            "run_id": index,
            "symbols": ",".join(symbols),
            **overrides,
            "closed_trades": report.get("closed_trades", 0),
            "win_rate": report.get("win_rate", 0.0),
            "profit_factor": report.get("profit_factor", 0.0),
            "expectancy": report.get("expectancy", 0.0),
            "average_winner": report.get("average_winner", 0.0),
            "average_loser": report.get("average_loser", 0.0),
            "max_drawdown": report.get("max_drawdown", 0.0),
            "sharpe": report.get("sharpe"),
            "best_ticker": report.get("best_ticker"),
            "worst_ticker": report.get("worst_ticker"),
            "best_time_of_day": report.get("best_time_of_day"),
            "worst_time_of_day": report.get("worst_time_of_day"),
            "losing_streak": report.get("losing_streak", 0),
            "latest_regime": result["latest_regime"].get("regime")
        }
        row["research_score"] = score_result(row)

        run_journal_rows = build_setup_journal(
            result["trade_rows"],
            run_id=index,
            config_overrides=overrides
        )
        journal_rows.extend(run_journal_rows)

        rows.append(row)

    quality_by_run = summarize_by_run(journal_rows)

    for row in rows:
        row.update(quality_by_run.get(row["run_id"], {
            "good_setup_good_outcome": 0,
            "bad_setup_bad_outcome": 0,
            "worked_but_review": 0,
            "failed_or_unclear": 0,
        }))

    return rows, journal_rows


def write_results(rows, journal_rows, output_dir):
    os.makedirs(output_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    raw_path = os.path.join(output_dir, f"raw_backtests_{timestamp}.csv")
    best_path = os.path.join(output_dir, f"best_configs_{timestamp}.csv")
    journal_path = os.path.join(output_dir, f"trade_setup_journal_{timestamp}.csv")
    summary_path = os.path.join(output_dir, f"setup_summary_{timestamp}.csv")

    data = pd.DataFrame(rows)
    data.to_csv(raw_path, index=False)

    ranked = data.sort_values("research_score", ascending=False)
    ranked.to_csv(best_path, index=False)

    print(f"Saved raw results: {raw_path}", flush=True)
    print(f"Saved ranked results: {best_path}", flush=True)

    journal_data = pd.DataFrame(journal_rows)
    if journal_data.empty:
        journal_data = pd.DataFrame(columns=JOURNAL_COLUMNS)
    journal_data.to_csv(journal_path, index=False)

    summary_data = pd.DataFrame(summarize_setup_journal(journal_rows))
    if summary_data.empty:
        summary_data = pd.DataFrame(columns=SUMMARY_COLUMNS)
    summary_data.to_csv(summary_path, index=False)

    print(f"Saved setup journal: {journal_path}", flush=True)
    print(f"Saved setup summary: {summary_path}", flush=True)

    if not ranked.empty:
        print("\nTop 10 configs:", flush=True)
        print(ranked.head(10).to_string(index=False), flush=True)


def maybe_download_data(args, symbols):
    if not args.download:
        return

    all_symbols = symbols[:]
    for symbol in DEFAULT_MARKET_SYMBOLS:
        if symbol not in all_symbols:
            all_symbols.append(symbol)

    print(f"Downloading data for {len(all_symbols)} symbols")

    for index in range(0, len(all_symbols), args.download_batch_size):
        batch = all_symbols[index:index + args.download_batch_size]
        print(f"Downloading batch: {', '.join(batch)}")
        fetch_and_save_bars(
            symbols=batch,
            start_date=args.start_date,
            end_date=args.end_date,
            output_dir=args.data_dir,
            feed=args.feed
        )


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--capital", type=float, default=100000.0)
    parser.add_argument("--pdt-floor", type=float, default=0.0)
    parser.add_argument("--data-dir", default="historical_data")
    parser.add_argument("--output-dir", default="research_results")
    parser.add_argument("--download", action="store_true")
    parser.add_argument("--feed", default="iex")
    parser.add_argument("--download-batch-size", type=int, default=50)
    parser.add_argument("--symbols", default="")
    parser.add_argument("--include-watchlist", action="store_true")
    parser.add_argument("--core-symbols", action="store_true")
    parser.add_argument("--etf-universe", action="store_true")
    parser.add_argument("--legacy-watchlist", action="store_true")
    parser.add_argument("--max-configs", type=int, default=0)

    parser.add_argument("--buy-start-times", default="10:30,11:00,11:15")
    parser.add_argument("--buy-end-times", default="13:30,14:30,15:15")
    parser.add_argument("--rsi-mins", default="45,50")
    parser.add_argument("--rsi-maxes", default="65,70,75")
    parser.add_argument("--rvol-mins", default="0.8,1.0,1.2")
    parser.add_argument("--require-breakout", default="true,false")
    parser.add_argument("--atr-stop-multiples", default="1.0,1.2,1.5")
    parser.add_argument("--atr-extreme-percents", default="0.015,0.02,0.025")
    parser.add_argument("--max-hold-minutes", default="45,60,90,120")
    parser.add_argument("--max-capital-per-trade", default="0.05,0.08,0.10")
    parser.add_argument("--max-positions", default="1,2,3")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    symbols = parse_symbols(args.symbols, args.include_watchlist, include_market=False)

    if args.etf_universe:
        symbols = ETF_RESEARCH_UNIVERSE
    elif args.legacy_watchlist:
        symbols = LEGACY_WATCHLIST
    elif args.core_symbols or not symbols:
        symbols = DEFAULT_CORE_SYMBOLS

    if args.include_watchlist:
        symbols = WATCHLIST

    print(f"Symbols: {', '.join(symbols)}", flush=True)
    print(f"Date range: {args.start_date} to {args.end_date}", flush=True)
    print(f"Starting capital: ${args.capital:,.2f}", flush=True)

    maybe_download_data(args, symbols)
    rows, journal_rows = run_grid(args, symbols)
    write_results(rows, journal_rows, args.output_dir)
