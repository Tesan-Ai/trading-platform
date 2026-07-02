"""Collect labeled training rows from historical backtests."""

from __future__ import annotations

from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

import config
from backtesting.profitability_replay import (
    _build_market_filter_frames,
    _build_market_feature_frame,
    _features_at_or_before,
    _is_entry_window_open,
    _prepare_feature_frame,
    _resolve_regime,
    build_timeline,
    load_symbol_data,
)
from features.daily_context import build_daily_regime_map
from ml_brain.feature_builder import build_feature_row, enrich_features_with_returns
from ml_brain.label_builder import build_labeled_row, label_candidate_from_forward_bars
from strategies.factory import get_strategy

EASTERN = ZoneInfo("America/New_York")


def collect_labeled_candidates(
    symbols: list[str],
    start_date: str,
    end_date: str,
    data_dir: str = "historical_data",
    market_filter_symbols: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Walk historical minute data, generate strategy-approved candidates, label forward."""
    strategy = get_strategy(config.ORVWAP_STRATEGY_NAME)
    market_filter_symbols = market_filter_symbols or [
        config.ORVWAP_MARKET_FILTER_SYMBOL,
        config.ORVWAP_TECH_FILTER_SYMBOL,
    ]
    all_symbols = list(dict.fromkeys(list(symbols) + market_filter_symbols))
    symbol_data = load_symbol_data(all_symbols, data_dir, start_date, end_date)
    if not symbol_data:
        return []

    featured = {
        symbol: _prepare_feature_frame(data_frame, strategy).dropna().reset_index(drop=True)
        for symbol, data_frame in symbol_data.items()
        if not data_frame.empty
    }
    featured = {symbol: frame for symbol, frame in featured.items() if not frame.empty}
    market_feature_frame = _build_market_feature_frame(symbol_data, strategy)
    market_filter_frames = _build_market_filter_frames(symbol_data, strategy)
    regime_source = symbol_data.get(config.MARKET_REGIME_SYMBOL)
    if regime_source is None or regime_source.empty:
        regime_source = next(iter(symbol_data.values()))
    daily_regime_map = build_daily_regime_map(regime_source)
    timeline = build_timeline(featured)
    labeled_rows: list[dict] = []

    for current_timestamp in timeline:
        if not _is_entry_window_open(strategy, current_timestamp):
            continue

        trade_date = current_timestamp.to_pydatetime().astimezone(EASTERN).date()
        regime = _resolve_regime(
            strategy,
            market_feature_frame,
            current_timestamp,
            daily_regime_map,
            trade_date,
            market_filter_frames,
        )

        for symbol in symbols:
            frame = featured.get(symbol)
            if frame is None:
                continue

            features = _features_at_or_before(symbol, frame, current_timestamp)
            if features is None:
                continue

            symbol_frame = symbol_data[symbol]
            idx = symbol_frame["timestamp"].searchsorted(current_timestamp, side="right")
            enriched = enrich_features_with_returns(features, symbol_frame.iloc[:idx])

            if not hasattr(strategy, "build_signal_context"):
                continue
            details = strategy.build_signal_context(symbol, enriched, regime)
            if not details.get("entry_approved"):
                continue

            entry_price = float(details["entry_price"])
            stop_price = float(details["stop_price"])
            target_price = float(details["target_price"])
            forward = symbol_frame.iloc[idx:].copy()
            if forward.empty:
                continue

            label_info = label_candidate_from_forward_bars(
                entry_price, stop_price, target_price, forward, side="LONG"
            )
            if label_info.get("label") is None:
                continue

            feature_row = build_feature_row(details, features=enriched, regime=regime)
            labeled_rows.append(build_labeled_row(feature_row, label_info))

    return labeled_rows


def labeled_rows_to_dataframe(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)
