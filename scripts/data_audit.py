"""PR-1 step 1: Verify whether IEX vs SIP feed volume differs materially.

Read-only. Does NOT overwrite any file in historical_data/. Pulls a small
recent window for a couple of symbols on both feeds and reports the ratio.

Usage:
    python scripts/data_audit.py --symbols NVDA AAPL --days 5
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame

from historical_data import get_data_client

EASTERN = ZoneInfo("America/New_York")


def fetch_volume(symbol: str, start, end, feed: str) -> pd.DataFrame:
    request = StockBarsRequest(
        symbol_or_symbols=[symbol],
        timeframe=TimeFrame.Minute,
        start=start,
        end=end,
        feed=feed,
    )
    response = get_data_client().get_stock_bars(request)
    rows = response.data.get(symbol, [])
    if not rows:
        return pd.DataFrame(columns=["timestamp", "volume"])
    return pd.DataFrame(
        [{"timestamp": bar.timestamp, "volume": float(bar.volume)} for bar in rows]
    )


def audit_symbol(symbol: str, start, end) -> dict:
    result = {"symbol": symbol}
    for feed in ("iex", "sip"):
        try:
            frame = fetch_volume(symbol, start, end, feed)
            result[f"{feed}_bars"] = len(frame)
            result[f"{feed}_total_volume"] = float(frame["volume"].sum()) if not frame.empty else 0.0
        except Exception as exc:  # noqa: BLE001
            result[f"{feed}_error"] = str(exc)
    iex_vol = result.get("iex_total_volume", 0.0)
    sip_vol = result.get("sip_total_volume", 0.0)
    result["sip_to_iex_ratio"] = (sip_vol / iex_vol) if iex_vol else None
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare IEX vs SIP feed volume (read-only)")
    parser.add_argument("--symbols", nargs="+", default=["NVDA"])
    parser.add_argument("--days", type=int, default=5, help="Trading days lookback ending 15+ min ago")
    args = parser.parse_args()

    end = datetime.now(EASTERN) - timedelta(minutes=20)
    start = end - timedelta(days=args.days)

    print(f"Auditing {args.symbols} from {start} to {end}\n")

    results = [audit_symbol(symbol.upper(), start, end) for symbol in args.symbols]
    frame = pd.DataFrame(results)
    print(frame.to_string(index=False))

    if "sip_error" in frame.columns and frame["sip_error"].notna().any():
        print(
            "\nNOTE: SIP feed errored for one or more symbols. This usually means your "
            "Alpaca plan/key does not have SIP entitlement. Free historical SIP requires "
            "the query end time to be >=15 minutes in the past (already applied above)."
        )


if __name__ == "__main__":
    main()
