"""Indicator helpers for ORB-PBC v1.0 (Opening Range Breakout Pullback Continuation).

All functions here are pure/stateless transforms over pandas DataFrames. They are
kept separate from the strategy state machine so both can be unit tested in
isolation, and so other future intraday strategies can reuse them.

Design notes / fidelity to the ORB-PBC spec:
- Session VWAP uses typical price (H+L+C)/3 on 1-minute bars, reset daily.
- The Opening Range is 09:30:00 through 09:44:59 ET (configurable length).
- EMA9/ATR14 on 5-minute bars are computed continuously across the series
  (not reset daily), matching the existing convention in
  ``features/session_features.py`` and ``features/feature_store.py``.
- Time-of-day matched cumulative RVOL divides today's cumulative volume
  (09:30 -> t) by the trailing 20-session average cumulative volume at the
  *same clock time* t. This deliberately does NOT use naive full-day average
  volume, per the spec's explicit warning.
- Daily ATR / ATR% used as a pre-market filter is shifted by one session so a
  symbol's own not-yet-complete trading day never leaks into its own filter
  (avoids lookahead bias in the backtest).
"""

from __future__ import annotations

from datetime import time

import numpy as np
import pandas as pd
from zoneinfo import ZoneInfo

from features.feature_store import calculate_atr

EASTERN = ZoneInfo("America/New_York")

MARKET_OPEN = time(9, 30)
MARKET_CLOSE = time(16, 0)


def regular_session_only(minute_df: pd.DataFrame) -> pd.DataFrame:
    """Filter 1-minute bars down to regular trading hours (09:30-16:00 ET, weekdays)."""
    if minute_df.empty:
        return minute_df.copy()

    frame = minute_df.copy()
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
    frame = frame.sort_values("timestamp").reset_index(drop=True)
    eastern = frame["timestamp"].dt.tz_convert(EASTERN)
    market_days = eastern.dt.weekday < 5
    market_times = eastern.dt.time
    mask = market_days & (market_times >= MARKET_OPEN) & (market_times <= MARKET_CLOSE)
    return frame[mask].reset_index(drop=True)


def add_session_vwap_1m(minute_df: pd.DataFrame) -> pd.DataFrame:
    """Session-reset VWAP on 1-minute bars using typical price = (H+L+C)/3."""
    frame = minute_df.copy()
    if frame.empty:
        frame["session_date"] = []
        frame["vwap"] = []
        frame["cum_vol"] = []
        return frame

    eastern = frame["timestamp"].dt.tz_convert(EASTERN)
    frame["session_date"] = eastern.dt.date
    typical_price = (frame["high"] + frame["low"] + frame["close"]) / 3.0
    price_volume = typical_price * frame["volume"]
    frame["cum_pv"] = price_volume.groupby(frame["session_date"]).cumsum()
    frame["cum_vol"] = (
        frame["volume"].groupby(frame["session_date"]).cumsum().replace(0, np.nan)
    )
    frame["vwap"] = frame["cum_pv"] / frame["cum_vol"]
    return frame


def resample_to_5min(minute_df: pd.DataFrame) -> pd.DataFrame:
    """Resample 1-minute OHLCV bars into 5-minute bars labeled by bar CLOSE time.

    Using ``label="right", closed="left"`` means the bar covering
    09:30:00-09:34:59 is labeled 09:35:00 -- i.e. it only becomes visible once
    it has fully completed. This is what prevents lookahead bias when the
    backtest engine looks up "the last completed 5-minute bar" at any given
    1-minute timestamp.
    """
    if minute_df.empty:
        return minute_df.copy()

    frame = minute_df.copy()
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
    frame = frame.sort_values("timestamp")
    eastern_index = pd.DatetimeIndex(frame["timestamp"]).tz_convert(EASTERN)
    frame = frame.set_index(eastern_index)

    bars = frame.resample("5min", label="right", closed="left").agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
    )
    bars = bars.dropna(subset=["open"]).reset_index()
    bars = bars.rename(columns={"index": "bar_end_et"})
    if "bar_end_et" not in bars.columns:
        bars = bars.rename(columns={bars.columns[0]: "bar_end_et"})
    bars["timestamp"] = bars["bar_end_et"].dt.tz_convert("UTC")
    bars["session_date"] = bars["bar_end_et"].dt.date
    bars["eastern_time"] = bars["bar_end_et"].dt.time
    return bars.reset_index(drop=True)


def attach_vwap_and_cumvol(bars_5m: pd.DataFrame, minute_vwap_df: pd.DataFrame) -> pd.DataFrame:
    """Attach session VWAP + cumulative session volume (as of bar close) to 5m bars."""
    if bars_5m.empty:
        bars_5m = bars_5m.copy()
        bars_5m["vwap"] = []
        bars_5m["cum_vol"] = []
        return bars_5m

    left = bars_5m.sort_values("timestamp")
    right = minute_vwap_df[["timestamp", "vwap", "cum_vol"]].sort_values("timestamp")
    merged = pd.merge_asof(left, right, on="timestamp", direction="backward")
    return merged


def compute_opening_range(minute_df: pd.DataFrame, minutes: int = 15) -> pd.DataFrame:
    """Compute ORH/ORL/OR-midpoint/OR-width per session date.

    Opening range window is [09:30, 09:30 + minutes) ET, i.e. 09:30:00
    through 09:44:59 for the default 15-minute range.
    """
    if minute_df.empty:
        return pd.DataFrame(columns=["session_date", "orh", "orl", "or_midpoint", "or_width"])

    eastern = minute_df["timestamp"].dt.tz_convert(EASTERN)
    session_date = eastern.dt.date
    minute_of_day = eastern.dt.hour * 60 + eastern.dt.minute
    open_minute = MARKET_OPEN.hour * 60 + MARKET_OPEN.minute
    or_mask = (minute_of_day >= open_minute) & (minute_of_day < open_minute + minutes)

    windowed = minute_df.loc[or_mask].copy()
    windowed["session_date"] = session_date[or_mask]
    if windowed.empty:
        return pd.DataFrame(columns=["session_date", "orh", "orl", "or_midpoint", "or_width"])

    grouped = windowed.groupby("session_date", as_index=False).agg(
        orh=("high", "max"), orl=("low", "min")
    )
    grouped["or_midpoint"] = (grouped["orh"] + grouped["orl"]) / 2.0
    grouped["or_width"] = grouped["orh"] - grouped["orl"]
    return grouped


def add_vwap_cross_count(bars_5m: pd.DataFrame) -> pd.DataFrame:
    """Running count, per session, of how many times close has crossed VWAP."""
    if bars_5m.empty:
        bars_5m = bars_5m.copy()
        bars_5m["vwap_cross_count"] = []
        return bars_5m

    frame = bars_5m.sort_values("timestamp").copy()
    sign = np.sign(frame["close"] - frame["vwap"])
    sign = sign.where(sign != 0, np.nan)
    sign = sign.groupby(frame["session_date"]).ffill()
    prev_sign = sign.groupby(frame["session_date"]).shift(1)
    crossed = sign.notna() & prev_sign.notna() & (sign != prev_sign)
    frame["vwap_cross_count"] = (
        crossed.groupby(frame["session_date"]).cumsum().fillna(0).astype(int)
    )
    return frame


def add_atr5m_percentile_threshold(
    bars_5m: pd.DataFrame, lookback_days: int = 20, quantile: float = 0.98
) -> pd.DataFrame:
    """98th percentile of the stock's own trailing 20-session ATR(5m) distribution.

    The threshold for "today" only uses the prior N sessions (never today's
    own bars), so the chaos filter cannot leak intraday information.
    """
    frame = bars_5m.copy()
    if frame.empty or "atr_5m" not in frame:
        frame["atr_5m_p98_20d"] = []
        return frame

    days = sorted(frame["session_date"].unique())
    values_by_day = {
        day: frame.loc[frame["session_date"] == day, "atr_5m"].dropna().to_numpy()
        for day in days
    }
    thresholds = {}
    for index, day in enumerate(days):
        window_days = days[max(0, index - lookback_days) : index]
        pool = (
            np.concatenate([values_by_day[d] for d in window_days if values_by_day[d].size])
            if window_days
            else np.array([])
        )
        thresholds[day] = float(np.percentile(pool, quantile * 100)) if pool.size >= 20 else np.nan

    frame["atr_5m_p98_20d"] = frame["session_date"].map(thresholds)
    return frame


def build_daily_context(minute_df: pd.DataFrame, atr_period: int = 14) -> pd.DataFrame:
    """Per-session daily OHLCV + ATR14 + previous close, shifted to avoid lookahead.

    Row for session date D exposes ``atr_d`` / ``prev_close`` as of the close
    of session D-1, plus D's own session open/first-15m stats needed for the
    gap-and-fade filter (which is knowable as soon as the opening range
    completes on day D, not before).
    """
    if minute_df.empty:
        return pd.DataFrame()

    frame = minute_df.copy()
    eastern = frame["timestamp"].dt.tz_convert(EASTERN)
    frame["session_date"] = eastern.dt.date

    daily = frame.groupby("session_date", as_index=False).agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
    ).sort_values("session_date").reset_index(drop=True)

    daily["atr_d_raw"] = calculate_atr(daily.rename(columns={"session_date": "date"}), atr_period)
    # Shift by one session: the ATR/close used to gate session D must only be
    # known as of the close of session D-1.
    daily["atr_d"] = daily["atr_d_raw"].shift(1)
    daily["prev_close"] = daily["close"].shift(1)
    daily["atr_d_pct"] = daily["atr_d"] / daily["prev_close"]
    daily["gap_dollars"] = daily["open"] - daily["prev_close"]
    daily["session_open"] = daily["open"]

    # 90th percentile of the trailing ~1 year (252 sessions) of ATR% history,
    # excluding today. With less than a year of history the window simply
    # widens as data accumulates (documented as a known data limitation).
    shifted_atr_pct = daily["atr_d_pct"].shift(1)
    daily["atr_d_pct_p90_1y"] = shifted_atr_pct.rolling(window=252, min_periods=20).quantile(0.90)

    return daily


def add_time_of_day_rvol(bars_5m: pd.DataFrame, lookback_days: int = 20) -> pd.DataFrame:
    """Time-of-day matched cumulative RVOL: today's cum_vol(t) / avg cum_vol(t) over trailing N sessions.

    This explicitly compares like-for-like clock times across sessions and
    must NOT be confused with a naive full-day average volume ratio.
    """
    frame = bars_5m.copy()
    if frame.empty:
        frame["rvol"] = []
        return frame

    frame["time_of_day"] = frame["eastern_time"]
    pivot = frame.pivot_table(
        index="session_date", columns="time_of_day", values="cum_vol", aggfunc="last"
    ).sort_index()
    avg_pivot = pivot.shift(1).rolling(window=lookback_days, min_periods=5).mean()
    avg_long = avg_pivot.stack(future_stack=True).rename("avg_cum_vol_20d").reset_index()
    avg_long.columns = ["session_date", "time_of_day", "avg_cum_vol_20d"]

    frame = frame.merge(avg_long, on=["session_date", "time_of_day"], how="left")
    frame["rvol"] = frame["cum_vol"] / frame["avg_cum_vol_20d"]
    return frame


def add_gap_and_fade_flag(daily_df: pd.DataFrame, first15_close_by_day: dict) -> pd.DataFrame:
    """Flag sessions where price gapped up hard then faded in the first 15 minutes.

    Condition (per spec): gap up > 1.0 * daily ATR AND the first 15-minute
    bar closes in the bottom third of its own range AND below the session
    open.
    """
    frame = daily_df.copy()
    if frame.empty:
        frame["gap_and_fade_flag"] = []
        return frame

    def _flag(row):
        day = row["session_date"]
        first15 = first15_close_by_day.get(day)
        if first15 is None or pd.isna(row.get("atr_d")) or pd.isna(row.get("gap_dollars")):
            return False
        gapped_up_hard = row["gap_dollars"] > float(row["atr_d"])
        if not gapped_up_hard:
            return False
        orh, orl, close = first15["orh"], first15["orl"], first15["close"]
        rng = orh - orl
        if rng <= 0:
            return False
        position_in_range = (close - orl) / rng
        closed_bottom_third = position_in_range <= (1.0 / 3.0)
        closed_below_open = close < row["session_open"]
        return bool(closed_bottom_third and closed_below_open)

    frame["gap_and_fade_flag"] = frame.apply(_flag, axis=1)
    return frame


def build_orb_pbc_feature_frame(
    minute_df: pd.DataFrame,
    opening_range_minutes: int = 15,
    rvol_lookback_days: int = 20,
    atr5m_lookback_days: int = 20,
    atr_period: int = 14,
) -> pd.DataFrame:
    """Build the full 5-minute-bar feature frame used by the ORB-PBC state machine.

    Returns a DataFrame of 5-minute bars (indexed implicitly, sorted by
    timestamp) with columns:

    timestamp, session_date, eastern_time, open, high, low, close, volume,
    vwap, cum_vol, orh, orl, or_midpoint, or_width, ema9_5m, atr_5m,
    atr_5m_p98_20d, vwap_cross_count, rvol, atr_d, prev_close, atr_d_pct,
    atr_d_pct_p90_1y, gap_and_fade_flag, or_complete, above_vwap
    """
    rth = regular_session_only(minute_df)
    if rth.empty:
        return pd.DataFrame()

    minute_vwap = add_session_vwap_1m(rth)
    bars_5m = resample_to_5min(rth)
    if bars_5m.empty:
        return bars_5m

    bars_5m = attach_vwap_and_cumvol(bars_5m, minute_vwap)
    bars_5m["above_vwap"] = bars_5m["close"] > bars_5m["vwap"]

    opening_range = compute_opening_range(rth, minutes=opening_range_minutes)
    bars_5m = bars_5m.merge(opening_range, on="session_date", how="left")
    or_end_minute = MARKET_OPEN.hour * 60 + MARKET_OPEN.minute + opening_range_minutes
    bar_minute = bars_5m["eastern_time"].apply(lambda value: value.hour * 60 + value.minute)
    bars_5m["or_complete"] = bar_minute >= or_end_minute

    close = bars_5m["close"]
    bars_5m["ema9_5m"] = close.ewm(span=9, adjust=False).mean()
    bars_5m["atr_5m"] = calculate_atr(bars_5m, atr_period)

    bars_5m = add_vwap_cross_count(bars_5m)
    bars_5m = add_atr5m_percentile_threshold(bars_5m, lookback_days=atr5m_lookback_days)
    bars_5m = add_time_of_day_rvol(bars_5m, lookback_days=rvol_lookback_days)

    daily = build_daily_context(rth, atr_period=atr_period)

    first15_close_by_day = {}
    or_bar_mask = bars_5m["or_complete"] & (
        bar_minute < or_end_minute + 5
    )  # the bar that completes the OR window itself
    for _, row in bars_5m.loc[or_bar_mask].iterrows():
        first15_close_by_day[row["session_date"]] = {
            "orh": row["orh"],
            "orl": row["orl"],
            "close": row["close"],
        }
    daily = add_gap_and_fade_flag(daily, first15_close_by_day)

    daily_cols = daily[
        [
            "session_date",
            "atr_d",
            "prev_close",
            "atr_d_pct",
            "atr_d_pct_p90_1y",
            "gap_and_fade_flag",
        ]
    ]
    bars_5m = bars_5m.merge(daily_cols, on="session_date", how="left")

    return bars_5m.sort_values("timestamp").reset_index(drop=True)
