from datetime import datetime, timedelta
from typing import Optional, Dict, Any

import pandas as pd
from zoneinfo import ZoneInfo

from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame

import config

EASTERN = ZoneInfo("America/New_York")

data_client = None


def get_data_client():
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


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(value, maximum))


def normalize_time(current_time: Optional[datetime]) -> datetime:
    if current_time is None:
        return datetime.now(EASTERN)

    if current_time.tzinfo is None:
        return current_time.replace(tzinfo=EASTERN)

    return current_time.astimezone(EASTERN)


def get_daily_trend_metrics(
    symbol: str,
    current_time: Optional[datetime] = None
) -> Optional[Dict[str, Any]]:
    current_time = normalize_time(current_time)
    start_time = current_time - timedelta(days=320)

    request = StockBarsRequest(
        symbol_or_symbols=symbol,
        timeframe=TimeFrame.Day,
        start=start_time,
        end=current_time,
        feed=config.ALPACA_DATA_FEED,
    )

    try:
        bars_response = get_data_client().get_stock_bars(request)
    except Exception as error:
        print(f"Failed to fetch daily bars for {symbol}: {error}")
        return None

    if symbol not in bars_response.data:
        return None

    bars = bars_response.data[symbol]

    if not bars:
        return None

    rows = []

    for bar in bars:
        rows.append({
            "timestamp": bar.timestamp,
            "open": float(bar.open),
            "high": float(bar.high),
            "low": float(bar.low),
            "close": float(bar.close),
            "volume": float(bar.volume)
        })

    daily_frame = pd.DataFrame(rows)
    daily_frame = daily_frame.sort_values("timestamp").reset_index(drop=True)

    if len(daily_frame) < 210:
        return None

    daily_frame["ma50"] = daily_frame["close"].rolling(50).mean()
    daily_frame["ma200"] = daily_frame["close"].rolling(200).mean()
    daily_frame["ma50_yesterday"] = daily_frame["ma50"].shift(1)

    daily_frame = daily_frame.dropna().reset_index(drop=True)

    if daily_frame.empty:
        return None

    latest_row = daily_frame.iloc[-1]

    close_price = float(latest_row["close"])
    ma50 = float(latest_row["ma50"])
    ma200 = float(latest_row["ma200"])
    ma50_yesterday = float(latest_row["ma50_yesterday"])

    distance_to_ma50 = (close_price - ma50) / ma50
    ma_spread = (ma50 - ma200) / ma200
    ma50_slope = 0.0

    if ma50_yesterday > 0:
        ma50_slope = (ma50 - ma50_yesterday) / ma50_yesterday

    is_uptrend = (
        close_price > ma200
        and ma50 > ma200
        and ma50 > ma50_yesterday
    )

    return {
        "symbol": symbol,
        "close": close_price,
        "ma50": ma50,
        "ma200": ma200,
        "ma50_yesterday": ma50_yesterday,
        "distance_to_ma50": distance_to_ma50,
        "ma_spread": ma_spread,
        "ma50_slope": ma50_slope,
        "is_uptrend": is_uptrend
    }


def add_features(data_frame: pd.DataFrame) -> pd.DataFrame:
    data_frame = data_frame.copy()

    if data_frame.empty or len(data_frame) < 35:
        return pd.DataFrame()

    data_frame["return_3m"] = data_frame["close"].pct_change(3)
    data_frame["return_5m"] = data_frame["close"].pct_change(5)
    data_frame["return_15m"] = data_frame["close"].pct_change(15)
    data_frame["return_30m"] = data_frame["close"].pct_change(30)

    data_frame["ema_9"] = data_frame["close"].ewm(span=9, adjust=False).mean()
    data_frame["ema_20"] = data_frame["close"].ewm(span=20, adjust=False).mean()
    data_frame["ema_ratio_fast"] = data_frame["ema_9"] / data_frame["ema_20"]

    data_frame["vol_avg_20"] = data_frame["volume"].rolling(20).mean()
    data_frame["relative_volume_20"] = data_frame["volume"] / data_frame["vol_avg_20"]

    cumulative_volume = data_frame["volume"].cumsum().replace(0, pd.NA)
    cumulative_price_volume = (data_frame["close"] * data_frame["volume"]).cumsum()

    data_frame["vwap"] = cumulative_price_volume / cumulative_volume
    data_frame["vwap_distance"] = (
        data_frame["close"] - data_frame["vwap"]
    ) / data_frame["vwap"]

    data_frame["low_20"] = data_frame["low"].rolling(20).min()
    data_frame["high_20"] = data_frame["high"].rolling(20).max()

    range_span_20 = (data_frame["high_20"] - data_frame["low_20"]).replace(0, pd.NA)

    data_frame["pullback_position_20"] = (
        (data_frame["close"] - data_frame["low_20"]) / range_span_20
    ).clip(0, 1)

    data_frame["bar_range_percent"] = (
        data_frame["high"] - data_frame["low"]
    ) / data_frame["close"]

    data_frame = data_frame.dropna().reset_index(drop=True)
    return data_frame


def score_data_frame(
    symbol: str,
    data_frame: pd.DataFrame,
    daily_trend: Optional[Dict[str, Any]] = None
) -> Optional[Dict[str, Any]]:
    featured = add_features(data_frame)

    if featured.empty or len(featured) < 2:
        return None

    if daily_trend is None:
        return None

    if not daily_trend["is_uptrend"]:
        return None

    latest_row = featured.iloc[-1]
    previous_row = featured.iloc[-2]

    close_price = float(latest_row["close"])
    return_3m = float(latest_row["return_3m"])
    return_5m = float(latest_row["return_5m"])
    return_15m = float(latest_row["return_15m"])
    return_30m = float(latest_row["return_30m"])
    ema_ratio_fast = float(latest_row["ema_ratio_fast"])
    relative_volume_20 = float(latest_row["relative_volume_20"])
    vwap_distance = float(latest_row["vwap_distance"])
    pullback_position_20 = float(latest_row["pullback_position_20"])
    bar_range_percent = float(latest_row["bar_range_percent"])

    previous_close = float(previous_row["close"])
    current_bar_green = close_price > previous_close

    distance_to_ma50 = float(daily_trend["distance_to_ma50"])
    ma50 = float(daily_trend["ma50"])
    ma200 = float(daily_trend["ma200"])
    ma_spread = float(daily_trend["ma_spread"])
    ma50_slope = float(daily_trend["ma50_slope"])

    score = 0.0

    score += clamp(ma_spread * 250, 0.0, 6.0)
    score += clamp(ma50_slope * 1200, 0.0, 4.0)

    score += clamp((0.04 - abs(distance_to_ma50)) * 140, -3.0, 4.0)

    if 0.0 <= distance_to_ma50 <= 0.03:
        score += 1.5

    score += clamp(return_3m * 180, -2.0, 3.5)
    score += clamp(return_5m * 220, -2.5, 4.0)
    score += clamp(return_15m * 140, -2.5, 3.5)
    score += clamp(return_30m * 90, -2.0, 2.5)

    score += clamp((ema_ratio_fast - 1.0) * 260, -2.0, 3.5)
    score += clamp(vwap_distance * 110, -2.0, 2.5)
    score += clamp((relative_volume_20 - 1.0) * 2.5, -1.5, 3.0)
    score += clamp((0.55 - pullback_position_20) * 4.0, -1.5, 1.5)

    if current_bar_green:
        score += 0.75
    else:
        score -= 0.75

    if return_3m <= -0.003:
        score -= 1.0

    if return_5m <= -0.004:
        score -= 1.5

    if ema_ratio_fast < 0.998:
        score -= 1.5

    if vwap_distance < -0.003:
        score -= 1.0

    if relative_volume_20 < 0.70:
        score -= 1.0

    if distance_to_ma50 < -0.035:
        score -= 3.0

    if distance_to_ma50 > 0.07:
        score -= 3.0

    if bar_range_percent > 0.035:
        score -= 0.75

    return {
        "symbol": symbol,
        "score": round(score, 2),
        "close": close_price,
        "return_3m": return_3m,
        "return_5m": return_5m,
        "return_15m": return_15m,
        "return_30m": return_30m,
        "ema_ratio": ema_ratio_fast,
        "relative_volume": relative_volume_20,
        "vwap_distance": vwap_distance,
        "pullback_position": pullback_position_20,
        "bar_range_percent": bar_range_percent,
        "distance_to_ma50": distance_to_ma50,
        "daily_ma50": ma50,
        "daily_ma200": ma200
    }


def build_trend_metrics_from_frame(
    symbol: str,
    data_frame: pd.DataFrame,
    short_window: int = 50,
    long_window: int = 200
) -> Optional[Dict[str, Any]]:
    if data_frame.empty or len(data_frame) < long_window + 2:
        return None

    trend_frame = data_frame.copy()
    trend_frame = trend_frame.sort_values("timestamp").reset_index(drop=True)
    trend_frame["ma50"] = trend_frame["close"].rolling(short_window).mean()
    trend_frame["ma200"] = trend_frame["close"].rolling(long_window).mean()
    trend_frame["ma50_yesterday"] = trend_frame["ma50"].shift(1)
    trend_frame = trend_frame.dropna().reset_index(drop=True)

    if trend_frame.empty:
        return None

    latest_row = trend_frame.iloc[-1]

    close_price = float(latest_row["close"])
    ma50 = float(latest_row["ma50"])
    ma200 = float(latest_row["ma200"])
    ma50_yesterday = float(latest_row["ma50_yesterday"])

    if ma50 <= 0 or ma200 <= 0:
        return None

    distance_to_ma50 = (close_price - ma50) / ma50
    ma_spread = (ma50 - ma200) / ma200
    ma50_slope = 0.0

    if ma50_yesterday > 0:
        ma50_slope = (ma50 - ma50_yesterday) / ma50_yesterday

    return {
        "symbol": symbol,
        "close": close_price,
        "ma50": ma50,
        "ma200": ma200,
        "ma50_yesterday": ma50_yesterday,
        "distance_to_ma50": distance_to_ma50,
        "ma_spread": ma_spread,
        "ma50_slope": ma50_slope,
        "is_uptrend": close_price > ma200 and ma50 > ma200 and ma50 > ma50_yesterday
    }


def fetch_bars_for_symbol(
    symbol: str,
    current_time: Optional[datetime] = None,
    minutes_back: Optional[int] = None
) -> pd.DataFrame:
    current_time = normalize_time(current_time)

    if minutes_back is None:
        minutes_back = getattr(config, "MODEL_MINUTES_BACK", 180)

    start_time = current_time - timedelta(minutes=minutes_back)

    request = StockBarsRequest(
        symbol_or_symbols=symbol,
        timeframe=TimeFrame.Minute,
        start=start_time,
        end=current_time,
        feed=config.ALPACA_DATA_FEED,
    )

    try:
        bars_response = get_data_client().get_stock_bars(request)
    except Exception as error:
        print(f"Failed to fetch bars for {symbol}: {error}")
        return pd.DataFrame()

    if symbol not in bars_response.data:
        return pd.DataFrame()

    bars = bars_response.data[symbol]

    if not bars:
        return pd.DataFrame()

    rows = []

    for bar in bars:
        rows.append({
            "timestamp": bar.timestamp,
            "open": float(bar.open),
            "high": float(bar.high),
            "low": float(bar.low),
            "close": float(bar.close),
            "volume": float(bar.volume)
        })

    if not rows:
        return pd.DataFrame()

    data_frame = pd.DataFrame(rows)
    data_frame = data_frame.sort_values("timestamp").reset_index(drop=True)
    return data_frame


def get_latest_price(symbol: str, current_time: Optional[datetime] = None) -> Optional[float]:
    data_frame = fetch_bars_for_symbol(
        symbol=symbol,
        current_time=current_time,
        minutes_back=15
    )

    if data_frame.empty:
        return None

    return float(data_frame.iloc[-1]["close"])


def score_stock(symbol: str, current_time: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
    daily_trend = get_daily_trend_metrics(symbol, current_time=current_time)

    if daily_trend is None or not daily_trend["is_uptrend"]:
        return None

    data_frame = fetch_bars_for_symbol(
        symbol=symbol,
        current_time=current_time,
        minutes_back=getattr(config, "MODEL_MINUTES_BACK", 180)
    )

    if data_frame.empty:
        return None

    return score_data_frame(symbol, data_frame, daily_trend)
