import pandas as pd


def calculate_rsi(close: pd.Series, period: int) -> pd.Series:
    delta = close.diff()
    gains = delta.clip(lower=0)
    losses = -delta.clip(upper=0)
    average_gain = gains.ewm(alpha=1 / period, adjust=False).mean()
    average_loss = losses.ewm(alpha=1 / period, adjust=False).mean()
    relative_strength = average_gain / average_loss.replace(0, pd.NA)
    return 100 - (100 / (1 + relative_strength))


def calculate_atr(data_frame: pd.DataFrame, period: int) -> pd.Series:
    previous_close = data_frame["close"].shift(1)
    true_range = pd.concat([
        data_frame["high"] - data_frame["low"],
        (data_frame["high"] - previous_close).abs(),
        (data_frame["low"] - previous_close).abs()
    ], axis=1).max(axis=1)
    return true_range.ewm(alpha=1 / period, adjust=False).mean()


def add_feature_columns(data_frame: pd.DataFrame, atr_period: int = 14) -> pd.DataFrame:
    featured = data_frame.copy()

    if featured.empty:
        return featured

    featured = featured.sort_values("timestamp").reset_index(drop=True)
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

    cumulative_volume = featured["volume"].cumsum().replace(0, pd.NA)
    cumulative_price_volume = (featured["close"] * featured["volume"]).cumsum()
    featured["vwap"] = cumulative_price_volume / cumulative_volume
    featured["vwap_distance"] = (featured["close"] - featured["vwap"]) / featured["vwap"]
    featured["above_vwap"] = featured["close"] > featured["vwap"]

    featured["atr_14"] = calculate_atr(featured, atr_period)
    featured["atr_percent"] = featured["atr_14"] / featured["close"]

    featured["volume_avg_20"] = featured["volume"].rolling(20).mean()
    featured["relative_volume"] = featured["volume"] / featured["volume_avg_20"]
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
    featured["spread_percent"] = 0.0

    return featured


def latest_features(symbol: str, data_frame: pd.DataFrame) -> dict | None:
    featured = add_feature_columns(data_frame)
    featured = featured.dropna().reset_index(drop=True)

    if featured.empty:
        return None

    latest_row = featured.iloc[-1].to_dict()
    latest_row["symbol"] = symbol
    return latest_row
