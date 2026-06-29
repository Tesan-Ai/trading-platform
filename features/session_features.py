from datetime import time

import pandas as pd
from zoneinfo import ZoneInfo

from features.feature_store import calculate_atr, calculate_rsi

EASTERN = ZoneInfo("America/New_York")
OR_START = time(9, 30)
OR_END = time(9, 35)
DEFAULT_ENTRY_START = time(9, 35)
DEFAULT_ENTRY_END = time(10, 30)


def add_session_feature_columns(
    data_frame: pd.DataFrame,
    atr_period: int = 14,
    entry_start: time = DEFAULT_ENTRY_START,
    entry_end: time = DEFAULT_ENTRY_END,
) -> pd.DataFrame:
    """Compute session-reset VWAP, opening range levels, and intraday entry flags."""
    featured = data_frame.copy()
    if featured.empty:
        return featured

    featured = featured.sort_values("timestamp").reset_index(drop=True)
    eastern = featured["timestamp"].dt.tz_convert(EASTERN)
    featured["session_date"] = eastern.dt.date
    featured["eastern_time"] = eastern.dt.time

    price_volume = featured["close"] * featured["volume"]
    featured["session_cum_pv"] = price_volume.groupby(featured["session_date"]).cumsum()
    featured["session_cum_vol"] = (
        featured["volume"].groupby(featured["session_date"]).cumsum().replace(0, pd.NA)
    )
    featured["vwap"] = featured["session_cum_pv"] / featured["session_cum_vol"]
    featured["vwap_distance"] = (featured["close"] - featured["vwap"]) / featured["vwap"]
    featured["above_vwap"] = featured["close"] > featured["vwap"]

    or_mask = (
        (eastern.dt.hour == 9)
        & (eastern.dt.minute >= OR_START.minute)
        & (eastern.dt.minute < OR_END.minute)
    )
    opening_range = (
        featured.loc[or_mask]
        .groupby("session_date", as_index=False)
        .agg(opening_range_high=("high", "max"), opening_range_low=("low", "min"))
    )
    featured = featured.merge(opening_range, on="session_date", how="left")
    featured["opening_range_midpoint"] = (
        featured["opening_range_high"] + featured["opening_range_low"]
    ) / 2.0

    close = featured["close"]
    featured["ema_9"] = close.ewm(span=9, adjust=False).mean()
    featured["ema_20"] = close.ewm(span=20, adjust=False).mean()
    featured["ema_50"] = close.ewm(span=50, adjust=False).mean()
    featured["ema_200"] = close.ewm(span=200, adjust=False).mean()
    featured["ema_9_slope"] = featured["ema_9"].pct_change(3)
    featured["ema_20_slope"] = featured["ema_20"].pct_change(3)

    featured["rsi_7"] = calculate_rsi(close, 7)
    featured["rsi_14"] = calculate_rsi(close, 14)

    ema_12 = close.ewm(span=12, adjust=False).mean()
    ema_26 = close.ewm(span=26, adjust=False).mean()
    featured["macd"] = ema_12 - ema_26
    featured["macd_signal"] = featured["macd"].ewm(span=9, adjust=False).mean()
    featured["macd_slope"] = featured["macd"].diff(3)

    featured["atr_14"] = calculate_atr(featured, atr_period)
    featured["atr_percent"] = featured["atr_14"] / featured["close"]
    featured["distance_from_vwap_atr"] = (featured["close"] - featured["vwap"]) / featured[
        "atr_14"
    ].replace(0, pd.NA)

    featured["volume_avg_20"] = featured["volume"].rolling(20).mean()
    featured["relative_volume"] = featured["volume"] / featured["volume_avg_20"]
    featured["volume_ratio"] = featured["relative_volume"]
    featured["volume_trend"] = featured["volume_avg_20"].pct_change(5)

    featured["resistance_20"] = featured["high"].rolling(20).max().shift(1)
    featured["support_20"] = featured["low"].rolling(20).min().shift(1)
    featured["breakout_distance"] = (
        featured["close"] - featured["resistance_20"]
    ) / featured["resistance_20"]
    featured["support_distance"] = (
        featured["close"] - featured["support_20"]
    ) / featured["close"]

    featured["bar_range_percent"] = (featured["high"] - featured["low"]) / featured["close"]
    featured["spread_percent"] = featured["bar_range_percent"] * 100.0

    featured["or_complete"] = featured["eastern_time"] >= OR_END
    featured["in_entry_window"] = featured["eastern_time"].apply(
        lambda bar_time: entry_start <= bar_time <= entry_end
    )
    featured["or_breakout_close"] = featured["or_complete"] & (
        featured["close"] > featured["opening_range_high"]
    )

    featured["prev_low"] = featured["low"].shift(1)
    featured["lower_low"] = featured["low"] < featured["prev_low"]
    featured["lower_lows_below_vwap"] = (
        featured["lower_low"] & ~featured["above_vwap"]
    )

    return featured


def latest_session_features(symbol: str, data_frame: pd.DataFrame) -> dict | None:
    featured = add_session_feature_columns(data_frame).dropna().reset_index(drop=True)
    if featured.empty:
        return None

    latest_row = featured.iloc[-1].to_dict()
    latest_row["symbol"] = symbol
    return latest_row
