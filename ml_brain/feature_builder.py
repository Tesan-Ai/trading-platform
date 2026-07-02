"""Build ML feature rows from OR/VWAP candidate trades.

Maps strategy signal context + session features + regime into a flat numeric
feature dict suitable for sklearn. Missing fields are filled with safe
defaults and tracked in ``missing_fields`` for observability.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd

import config

# Numeric columns fed to sklearn (order matters — persisted with model artifact).
NUMERIC_FEATURE_COLUMNS = [
    "vwap_distance",
    "opening_range_high",
    "opening_range_low",
    "breakout_strength",
    "relative_volume",
    "volume_spike",
    "atr",
    "spy_trend",
    "qqq_trend",
    "market_regime_on",
    "hour_of_day",
    "minute_of_day",
    "day_of_week",
    "return_1m",
    "return_5m",
    "return_15m",
    "spread_pct",
]

CATEGORICAL_COLUMNS = ["symbol", "side", "strategy_name"]


def _safe_float(value, default=0.0) -> float:
    if value is None:
        return float(default)
    try:
        if value != value:  # NaN
            return float(default)
    except TypeError:
        pass
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _parse_timestamp(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return pd.to_datetime(value, utc=True).to_pydatetime()
    except (TypeError, ValueError):
        return None


def build_feature_row(
    candidate_trade: dict,
    features: dict | None = None,
    regime: dict | None = None,
) -> dict[str, Any]:
    """Build one feature row from a candidate trade payload.

    ``candidate_trade`` is typically the dict returned by
    ``OpeningRangeVwapMomentumStrategy.build_signal_context()``.
    Optional ``features`` / ``regime`` override or supplement nested values.
    """
    features = features or {}
    regime = regime or {}
    missing: list[str] = []

    symbol = candidate_trade.get("ticker") or candidate_trade.get("symbol") or "UNKNOWN"
    side = candidate_trade.get("side") or "LONG"
    strategy_name = (
        candidate_trade.get("strategy_name")
        or candidate_trade.get("strategy_version")
        or config.ORVWAP_STRATEGY_NAME
    )

    ts = _parse_timestamp(candidate_trade.get("timestamp") or features.get("timestamp"))
    hour_of_day = float(ts.hour) if ts else 0.0
    minute_of_day = float(ts.hour * 60 + ts.minute) if ts else 0.0
    day_of_week = float(ts.weekday()) if ts else 0.0

    orh = candidate_trade.get("opening_range_high") or features.get("opening_range_high")
    orl = candidate_trade.get("opening_range_low") or features.get("opening_range_low")
    close = _safe_float(candidate_trade.get("price") or features.get("close"))

    if orh is None:
        missing.append("opening_range_high")
    if orl is None:
        missing.append("opening_range_low")

    breakout_strength = 0.0
    if orh is not None and orh:
        breakout_strength = (close - float(orh)) / float(orh)

    vwap_distance = candidate_trade.get("distance_from_vwap")
    if vwap_distance is None:
        vwap_distance = features.get("vwap_distance")
    if vwap_distance is None:
        vwap = candidate_trade.get("vwap") or features.get("vwap")
        if vwap is not None:
            vwap_distance = (close - float(vwap)) / close if close else 0.0
        else:
            missing.append("vwap_distance")

    relative_volume = candidate_trade.get("volume_ratio") or features.get("volume_ratio")
    if relative_volume is None:
        relative_volume = features.get("relative_volume")
    if relative_volume is None:
        missing.append("relative_volume")

    volume_spike = relative_volume if relative_volume is not None else 0.0

    atr = candidate_trade.get("atr") or features.get("atr_14") or features.get("atr")
    if atr is None:
        missing.append("atr")

    spy_trend = 1.0 if regime.get("spy_above_vwap", candidate_trade.get("spy_above_vwap")) else 0.0
    qqq_trend = 1.0 if regime.get("qqq_above_vwap", candidate_trade.get("qqq_above_vwap")) else 0.0
    market_regime_on = 1.0 if regime.get("trade_allowed", True) else 0.0

    spread = candidate_trade.get("spread") or features.get("spread_percent")
    if spread is None:
        missing.append("spread")

    return_1m = features.get("return_1m")
    return_5m = features.get("return_5m")
    return_15m = features.get("return_15m")
    for name, value in [("return_1m", return_1m), ("return_5m", return_5m), ("return_15m", return_15m)]:
        if value is None:
            missing.append(name)

    row = {
        "timestamp": ts.isoformat() if ts else None,
        "symbol": symbol,
        "side": side,
        "strategy_name": strategy_name,
        "entry_price": _safe_float(candidate_trade.get("entry_price") or close),
        "vwap_distance": _safe_float(vwap_distance),
        "opening_range_high": _safe_float(orh),
        "opening_range_low": _safe_float(orl),
        "breakout_strength": _safe_float(breakout_strength),
        "relative_volume": _safe_float(relative_volume),
        "volume_spike": _safe_float(volume_spike),
        "atr": _safe_float(atr),
        "spy_trend": spy_trend,
        "qqq_trend": qqq_trend,
        "market_regime_on": market_regime_on,
        "hour_of_day": hour_of_day,
        "minute_of_day": minute_of_day,
        "day_of_week": day_of_week,
        "return_1m": _safe_float(return_1m),
        "return_5m": _safe_float(return_5m),
        "return_15m": _safe_float(return_15m),
        "spread_pct": _safe_float(spread),
        "missing_fields": missing,
        "candidate_id": candidate_trade.get("candidate_id"),
    }
    return row


def feature_vector(row: dict) -> list[float]:
    """Return numeric feature vector in training column order."""
    return [_safe_float(row.get(column)) for column in NUMERIC_FEATURE_COLUMNS]


def enrich_features_with_returns(features: dict, frame: pd.DataFrame) -> dict:
    """Add return_1m / return_5m / return_15m from a minute OHLCV frame if missing."""
    if frame is None or frame.empty:
        return features

    enriched = dict(features)
    close = pd.to_numeric(frame["close"], errors="coerce")
    if len(close) >= 2:
        enriched.setdefault("return_1m", float(close.iloc[-1] / close.iloc[-2] - 1.0))
    if len(close) >= 6:
        enriched.setdefault("return_5m", float(close.iloc[-1] / close.iloc[-6] - 1.0))
    if len(close) >= 16:
        enriched.setdefault("return_15m", float(close.iloc[-1] / close.iloc[-16] - 1.0))
    return enriched
