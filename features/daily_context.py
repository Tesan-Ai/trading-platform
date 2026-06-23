from zoneinfo import ZoneInfo

import pandas as pd

EASTERN = ZoneInfo("America/New_York")

BULL_TREND = "BULL_TREND"
BEAR_TREND = "BEAR_TREND"
CHOP = "CHOP"
INSUFFICIENT = "INSUFFICIENT"


def build_daily_bars(minute_frame: pd.DataFrame) -> pd.DataFrame:
    if minute_frame is None or minute_frame.empty:
        return pd.DataFrame()

    frame = minute_frame.copy()
    frame["date"] = frame["timestamp"].dt.tz_convert(EASTERN).dt.date
    daily = frame.groupby("date", as_index=False).agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
    )
    daily["timestamp"] = pd.to_datetime(daily["date"])
    return daily.sort_values("date").reset_index(drop=True)


def add_daily_indicators(daily_frame: pd.DataFrame) -> pd.DataFrame:
    if daily_frame is None or daily_frame.empty:
        return pd.DataFrame()

    featured = daily_frame.copy()
    close = featured["close"]
    featured["ema_20"] = close.ewm(span=20, adjust=False).mean()
    featured["ema_50"] = close.ewm(span=50, adjust=False).mean()
    featured["ema_200"] = close.ewm(span=200, adjust=False).mean()
    featured["ema_20_slope"] = featured["ema_20"].pct_change(3)
    return featured


def classify_daily_row(row) -> dict:
    if row is None or pd.isna(row.get("ema_200")):
        return {
            "regime": INSUFFICIENT,
            "trade_allowed": False,
            "reason": "insufficient daily history",
        }

    close = float(row["close"])
    ema_20 = float(row["ema_20"])
    ema_50 = float(row["ema_50"])
    ema_200 = float(row["ema_200"])
    ema_20_slope = float(row.get("ema_20_slope", 0.0) or 0.0)

    if close > ema_50 > ema_200 and ema_20_slope >= 0:
        return {
            "regime": BULL_TREND,
            "trade_allowed": True,
            "reason": "daily bull trend",
        }

    if close < ema_20 < ema_50 and ema_20_slope < 0:
        return {
            "regime": BEAR_TREND,
            "trade_allowed": False,
            "reason": "daily bear trend",
        }

    return {
        "regime": CHOP,
        "trade_allowed": False,
        "reason": "daily chop",
    }


def build_daily_regime_map(minute_frame: pd.DataFrame) -> dict:
    daily = add_daily_indicators(build_daily_bars(minute_frame))
    if daily.empty:
        return {}

    regimes = {}
    for index, row in daily.iterrows():
        regimes[row["date"]] = classify_daily_row(row)

    return regimes


def daily_regime_for_date(regime_map: dict, trade_date, lag_days: int = 1) -> dict:
    if not regime_map:
        return {
            "regime": INSUFFICIENT,
            "trade_allowed": False,
            "reason": "missing daily regime map",
        }

    ordered_dates = sorted(regime_map.keys())
    if trade_date not in ordered_dates:
        prior_dates = [item for item in ordered_dates if item < trade_date]
        if not prior_dates:
            return {
                "regime": INSUFFICIENT,
                "trade_allowed": False,
                "reason": "no prior daily history",
            }
        trade_date = prior_dates[-1]

    index = ordered_dates.index(trade_date)
    source_index = index - lag_days
    if source_index < 0:
        return {
            "regime": INSUFFICIENT,
            "trade_allowed": False,
            "reason": "insufficient lagged daily history",
        }

    return regime_map[ordered_dates[source_index]]
