import argparse
import os
import tempfile

import pandas as pd

from backtest_runner import print_results
from replay_engine import run_replay


DEFAULT_SYMBOLS = [
    "AAPL", "MSFT", "NVDA", "AMD", "META",
    "TSLA", "AMZN", "PLTR", "SOFI", "RKLB"
]


def filter_day_data(symbols, source_dir, output_dir, replay_date):
    available_symbols = []

    for symbol in symbols:
        source_path = os.path.join(source_dir, f"{symbol}.csv")
        if not os.path.exists(source_path):
            continue

        data_frame = pd.read_csv(source_path)
        data_frame["timestamp"] = pd.to_datetime(data_frame["timestamp"], utc=True)
        eastern_dates = data_frame["timestamp"].dt.tz_convert("America/New_York").dt.date
        day_frame = data_frame[eastern_dates == replay_date].copy()

        if day_frame.empty:
            continue

        day_frame.to_csv(os.path.join(output_dir, f"{symbol}.csv"), index=False)
        available_symbols.append(symbol)

    return available_symbols


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True, help="Replay date in YYYY-MM-DD format")
    parser.add_argument("--capital", type=float, default=25000.0)
    parser.add_argument("--data-dir", default="historical_data")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    replay_date = pd.Timestamp(args.date).date()

    with tempfile.TemporaryDirectory() as temp_dir:
        symbols = filter_day_data(
            DEFAULT_SYMBOLS,
            args.data_dir,
            temp_dir,
            replay_date
        )

        print(f"One-day replay date: {args.date}")
        print(f"Starting capital: ${args.capital:,.2f}")
        print("Buy window: current config")
        print(f"Symbols with local data: {len(symbols)}")

        if not symbols:
            print("No local historical candles found for that date.")
            raise SystemExit(0)

        portfolio = run_replay(
            symbols=symbols,
            data_dir=temp_dir,
            starting_cash=args.capital
        )
        print_results(portfolio)
