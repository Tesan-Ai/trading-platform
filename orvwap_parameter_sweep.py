import argparse
import csv
import itertools
import json
import os
from contextlib import contextmanager

import config
from analytics.orvwap_report import build_orvwap_report
from backtesting.profitability_replay import run_profitability_replay
from strategies.factory import get_strategy


VOLUME_RATIO_MIN = [1.8, 2.0, 2.2, 2.5, 3.0]
MAX_ATR_EXTENSION = [1.0, 1.25, 1.5]
ENTRY_WINDOW_END = ["10:00", "10:15", "10:30"]
MAX_TRADES_PER_DAY = [1, 2, 3]
TAKE_PROFIT_R = [1.5, 2.0, 2.5]


def resolve_symbols() -> list[str]:
    configured = list(getattr(config, "TRADE_SYMBOLS", []))
    return configured or list(config.ORVWAP_TRADE_SYMBOLS)


@contextmanager
def patched_config(**values):
    original = {name: getattr(config, name) for name in values}
    try:
        for name, value in values.items():
            setattr(config, name, value)
        yield
    finally:
        for name, value in original.items():
            setattr(config, name, value)


def run_config(index: int, params: dict, args) -> dict:
    data_symbols = list(
        dict.fromkeys(resolve_symbols() + [config.ORVWAP_MARKET_FILTER_SYMBOL, config.ORVWAP_TECH_FILTER_SYMBOL])
    )
    with patched_config(
        ACTIVE_STRATEGY=config.ORVWAP_STRATEGY_NAME,
        ORVWAP_MIN_VOLUME_RATIO=params["volume_ratio_min"],
        ORVWAP_MAX_VWAP_EXTENSION_ATR=params["max_atr_extension_from_vwap"],
        ORVWAP_ENTRY_END=params["entry_window_end"],
        ORVWAP_MAX_TRADES_PER_DAY=params["max_trades_per_day"],
        ORVWAP_TARGET_R=params["take_profit_r"],
        TRADE_SYMBOLS=resolve_symbols(),
    ):
        result = run_profitability_replay(
            symbols=data_symbols,
            data_dir=args.data_dir,
            starting_cash=args.capital,
            start_date=args.start_date,
            end_date=args.end_date,
            strategy=get_strategy(config.ORVWAP_STRATEGY_NAME),
        )
    report = build_orvwap_report(result["trade_rows"], result["portfolio"].equity_curve, result.get("signal_rows"))
    starting = float(result["portfolio"].equity_curve[0]["equity"]) if result["portfolio"].equity_curve else args.capital
    ending = float(result["portfolio"].equity_curve[-1]["equity"]) if result["portfolio"].equity_curve else args.capital
    row = {
        "config_name": f"orvwap_sweep_{index:03d}",
        **params,
        "starting_equity": starting,
        "ending_equity": ending,
        "total_return": (ending - starting) / starting if starting else 0.0,
        "closed_trades": report.get("closed_trades", 0),
        "win_rate": report.get("win_rate", 0.0),
        "profit_factor": report.get("profit_factor", 0.0),
        "expectancy": report.get("expectancy", 0.0),
        "average_r": report.get("average_r", 0.0),
        "max_drawdown": report.get("max_drawdown", 0.0),
        "average_hold_time": report.get("average_hold_time", 0.0),
    }
    row["score"] = balanced_score(row, min_trades=args.min_trades)
    row["research_candidate_only"] = True
    row["sample_warning"] = "Not enough sample size to trust optimization yet." if row["closed_trades"] < args.min_trades else ""
    return row


def balanced_score(row: dict, min_trades: int = 20) -> float:
    trade_factor = min(float(row["closed_trades"]) / float(min_trades), 1.0)
    if row["closed_trades"] < max(5, min_trades // 2):
        trade_factor *= 0.25
    profit_factor = min(float(row.get("profit_factor") or 0.0), 3.0) / 3.0
    expectancy = max(min(float(row.get("expectancy") or 0.0) / 5.0, 1.0), -1.0)
    average_r = max(min(float(row.get("average_r") or 0.0), 1.0), -1.0)
    drawdown_score = 1.0 - min(float(row.get("max_drawdown") or 0.0) / 0.05, 1.0)
    return round(
        trade_factor
        * (
            35.0 * profit_factor
            + 25.0 * ((expectancy + 1.0) / 2.0)
            + 20.0 * ((average_r + 1.0) / 2.0)
            + 20.0 * drawdown_score
        ),
        4,
    )


def build_param_grid(limit: int | None = None):
    grid = itertools.product(
        VOLUME_RATIO_MIN,
        MAX_ATR_EXTENSION,
        ENTRY_WINDOW_END,
        MAX_TRADES_PER_DAY,
        TAKE_PROFIT_R,
    )
    for index, values in enumerate(grid, start=1):
        if limit is not None and index > limit:
            return
        yield index, {
            "volume_ratio_min": values[0],
            "max_atr_extension_from_vwap": values[1],
            "entry_window_end": values[2],
            "max_trades_per_day": values[3],
            "take_profit_r": values[4],
        }


def main():
    parser = argparse.ArgumentParser(description="Safe ORVWAP parameter sweep. Research only; does not activate configs.")
    parser.add_argument("--start-date", default="2025-09-03")
    parser.add_argument("--end-date", default="2026-06-03")
    parser.add_argument("--capital", type=float, default=float(config.INITIAL_CAPITAL))
    parser.add_argument("--data-dir", default="historical_data")
    parser.add_argument("--output-dir", default="research_results_orvwap")
    parser.add_argument("--limit", type=int, default=None, help="Limit configs for quick smoke runs.")
    parser.add_argument("--min-trades", type=int, default=20)
    args = parser.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)
    rows = []
    for index, params in build_param_grid(args.limit):
        row = run_config(index, params, args)
        rows.append(row)
        print(
            f"{row['config_name']} trades={row['closed_trades']} "
            f"pf={row['profit_factor']:.2f} exp={row['expectancy']:.2f} score={row['score']:.2f}"
        )

    rows.sort(key=lambda item: item["score"], reverse=True)
    csv_path = os.path.join(args.output_dir, "orvwap_parameter_sweep.csv")
    json_path = os.path.join(args.output_dir, "orvwap_parameter_sweep.json")
    if rows:
        with open(csv_path, "w", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(file, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
    with open(json_path, "w", encoding="utf-8") as file:
        json.dump({"research_only": True, "min_trades": args.min_trades, "results": rows}, file, indent=2)

    print(f"\nSaved sweep CSV:  {csv_path}")
    print(f"Saved sweep JSON: {json_path}")
    print("Top configs are research candidates only. Do not activate without walk-forward/paper validation.")


if __name__ == "__main__":
    main()
