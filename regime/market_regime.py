from features.feature_store import add_feature_columns


BULL_TREND = "BULL_TREND"
BEAR_TREND = "BEAR_TREND"
CHOP = "CHOP"
HIGH_VOLATILITY = "HIGH_VOLATILITY"
LOW_LIQUIDITY = "LOW_LIQUIDITY"
RISK_OFF = "RISK_OFF"


def classify_market_regime(market_frame):
    if market_frame is None or market_frame.empty or len(market_frame) < 220:
        return {
            "regime": CHOP,
            "trade_allowed": False,
            "reason": "insufficient market history"
        }

    featured = add_feature_columns(market_frame).dropna().reset_index(drop=True)

    if featured.empty:
        return {
            "regime": CHOP,
            "trade_allowed": False,
            "reason": "missing market features"
        }

    latest = featured.iloc[-1]

    close = float(latest["close"])
    ema_20 = float(latest["ema_20"])
    ema_50 = float(latest["ema_50"])
    ema_200 = float(latest["ema_200"])
    ema_20_slope = float(latest["ema_20_slope"])
    atr_percent = float(latest["atr_percent"])
    relative_volume = float(latest["relative_volume"])

    if relative_volume < 0.30:
        return {
            "regime": LOW_LIQUIDITY,
            "trade_allowed": False,
            "reason": "market liquidity too low"
        }

    if atr_percent > 0.025:
        return {
            "regime": HIGH_VOLATILITY,
            "trade_allowed": False,
            "reason": "market volatility expanded"
        }

    if close < ema_50 and ema_20 < ema_50 and ema_20_slope < 0:
        return {
            "regime": RISK_OFF,
            "trade_allowed": False,
            "reason": "market risk off"
        }

    if close > ema_20 > ema_50 > ema_200 and ema_20_slope > 0:
        return {
            "regime": BULL_TREND,
            "trade_allowed": True,
            "reason": "bull trend"
        }

    if close < ema_20 < ema_50 and ema_20_slope < 0:
        return {
            "regime": BEAR_TREND,
            "trade_allowed": False,
            "reason": "bear trend"
        }

    return {
        "regime": CHOP,
        "trade_allowed": False,
        "reason": "market is choppy"
    }
