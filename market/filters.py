import config
from features.session_features import latest_session_features


def evaluate_orvwap_market_filter(symbol_frames: dict) -> dict:
    spy_frame = symbol_frames.get(config.ORVWAP_MARKET_FILTER_SYMBOL)
    qqq_frame = symbol_frames.get(config.ORVWAP_TECH_FILTER_SYMBOL)
    if spy_frame is None or spy_frame.empty:
        return {
            "allowed": False,
            "regime": "UNKNOWN",
            "spy_status": "missing",
            "qqq_status": "unknown",
            "spy_above_vwap": False,
            "qqq_above_vwap": False,
            "reason": "missing SPY market data",
        }

    spy_features = latest_session_features(config.ORVWAP_MARKET_FILTER_SYMBOL, spy_frame)
    qqq_features = (
        latest_session_features(config.ORVWAP_TECH_FILTER_SYMBOL, qqq_frame)
        if qqq_frame is not None and not qqq_frame.empty
        else None
    )
    spy_above_vwap = bool(spy_features and spy_features.get("above_vwap"))
    qqq_above_vwap = bool(qqq_features.get("above_vwap")) if qqq_features else False
    spy_lower_lows = bool(spy_features and spy_features.get("lower_lows_below_vwap"))

    if not spy_above_vwap:
        reason = "SPY below VWAP"
    elif spy_lower_lows:
        reason = "SPY making lower lows below VWAP"
    else:
        reason = "SPY above VWAP"

    allowed = spy_above_vwap and not spy_lower_lows
    return {
        "allowed": allowed,
        "regime": "BULL_INTRADAY" if allowed else "RISK_OFF",
        "spy_status": "above_vwap" if spy_above_vwap else "below_vwap",
        "qqq_status": "above_vwap" if qqq_above_vwap else "below_vwap",
        "spy_above_vwap": spy_above_vwap,
        "qqq_above_vwap": qqq_above_vwap,
        "reason": reason,
    }
