from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import List
import os

import pandas as pd

from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame

import config


EASTERN = ZoneInfo("America/New_York")

data_client = None


def get_data_client() -> StockHistoricalDataClient:
    global data_client

    if data_client is not None:
        return data_client

    if not config.ALPACA_API_KEY or not config.ALPACA_SECRET_KEY:
        raise RuntimeError("Set ALPACA_API_KEY and ALPACA_SECRET_KEY in .env")

    data_client = StockHistoricalDataClient(
        api_key=config.ALPACA_API_KEY,
        secret_key=config.ALPACA_SECRET_KEY
    )
    return data_client


def ensure_directory(path: str) -> None:
    if not os.path.exists(path):
        os.makedirs(path)


def fetch_and_save_bars(
    symbols: List[str],
    start_date: str,
    end_date: str,
    output_dir: str = "historical_data",
    feed: str = "iex"
) -> None:
    ensure_directory(output_dir)

    start_time = datetime.fromisoformat(start_date).replace(tzinfo=EASTERN)
    end_time = datetime.fromisoformat(end_date).replace(tzinfo=EASTERN) + timedelta(days=1)

    request = StockBarsRequest(
        symbol_or_symbols=symbols,
        timeframe=TimeFrame.Minute,
        start=start_time,
        end=end_time,
        feed=feed
    )

    bars_response = get_data_client().get_stock_bars(request)

    for symbol in symbols:
        if symbol not in bars_response.data:
            print(f"No data for {symbol}")
            continue

        rows = []

        for bar in bars_response.data[symbol]:
            rows.append({
                "timestamp": bar.timestamp,
                "open": float(bar.open),
                "high": float(bar.high),
                "low": float(bar.low),
                "close": float(bar.close),
                "volume": float(bar.volume)
            })

        if not rows:
            print(f"No rows for {symbol}")
            continue

        data_frame = pd.DataFrame(rows)
        data_frame = data_frame.sort_values("timestamp").reset_index(drop=True)

        file_path = os.path.join(output_dir, f"{symbol}.csv")
        data_frame.to_csv(file_path, index=False)
        print(f"Saved {symbol} -> {file_path}")
