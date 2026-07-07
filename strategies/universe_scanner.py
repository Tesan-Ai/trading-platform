"""Daily 'stocks in play' universe scanner for research backtests.

Ranks a broad candidate pool each session by opening-range relative volume
(cumulative volume in the first N minutes vs the trailing same-window average),
then returns the top N symbols for that day. This replaces trading a fixed
7-symbol list on every session with catalyst-driven day selection.

Research mode only — no live/paper wiring yet.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import date, datetime, time
from pathlib import Path
from typing import Any

import pandas as pd
from zoneinfo import ZoneInfo

import config
from backtesting.profitability_replay import load_symbol_data
from features.intraday_indicators import build_daily_context, regular_session_only
from watchlist import SCANNER_UNIVERSE

EASTERN = ZoneInfo("America/New_York")
MARKET_OPEN = time(9, 30)


@dataclass(frozen=True)
class ScannerConfig:
    top_n: int = 10
    min_price: float = 5.0
    min_opening_rvol: float = 1.5
    opening_range_minutes: int = 5
    rvol_lookback_days: int = 14
    min_atr_d_pct: float = 0.015


def scanner_config_from_env() -> ScannerConfig:
    return ScannerConfig(
        top_n=int(getattr(config, "SCANNER_TOP_N", 10)),
        min_price=float(getattr(config, "SCANNER_MIN_PRICE", 5.0)),
        min_opening_rvol=float(getattr(config, "SCANNER_MIN_OPENING_RVOL", 1.5)),
        opening_range_minutes=int(getattr(config, "SCANNER_OR_MINUTES", 5)),
        rvol_lookback_days=int(getattr(config, "SCANNER_RVOL_LOOKBACK_DAYS", 14)),
        min_atr_d_pct=float(getattr(config, "SCANNER_MIN_ATR_D_PCT", 0.015)),
    )


def resolve_available_candidates(
    data_dir: str,
    candidates: list[str] | None = None,
) -> list[str]:
    """Return candidate symbols that have a CSV on disk."""
    pool = candidates or list(SCANNER_UNIVERSE)
    available = []
    for symbol in pool:
        path = os.path.join(data_dir, f"{symbol.upper()}.csv")
        if os.path.exists(path):
            available.append(symbol.upper())
    return sorted(set(available))


def _opening_range_volume(minute_df: pd.DataFrame, opening_range_minutes: int) -> pd.Series:
    """Per-session cumulative volume in [09:30, 09:30 + opening_range_minutes)."""
    frame = regular_session_only(minute_df)
    if frame.empty:
        return pd.Series(dtype=float)

    eastern = frame["timestamp"].dt.tz_convert(EASTERN)
    session_date = eastern.dt.date
    minute_of_day = eastern.dt.hour * 60 + eastern.dt.minute
    open_minute = MARKET_OPEN.hour * 60 + MARKET_OPEN.minute
    or_mask = (minute_of_day >= open_minute) & (minute_of_day < open_minute + opening_range_minutes)

    windowed = frame.loc[or_mask].copy()
    windowed["session_date"] = session_date[or_mask]
    if windowed.empty:
        return pd.Series(dtype=float)

    return windowed.groupby("session_date")["volume"].sum()


def _price_at_or_end(minute_df: pd.DataFrame, opening_range_minutes: int) -> pd.Series:
    frame = regular_session_only(minute_df)
    if frame.empty:
        return pd.Series(dtype=float)

    eastern = frame["timestamp"].dt.tz_convert(EASTERN)
    session_date = eastern.dt.date
    minute_of_day = eastern.dt.hour * 60 + eastern.dt.minute
    open_minute = MARKET_OPEN.hour * 60 + MARKET_OPEN.minute
    or_end_minute = open_minute + opening_range_minutes - 1
    end_mask = minute_of_day == or_end_minute

    windowed = frame.loc[end_mask].copy()
    windowed["session_date"] = session_date[end_mask]
    if windowed.empty:
        # Fall back to last bar inside the opening range window.
        or_mask = (minute_of_day >= open_minute) & (minute_of_day < open_minute + opening_range_minutes)
        windowed = frame.loc[or_mask].copy()
        windowed["session_date"] = session_date[or_mask]
        if windowed.empty:
            return pd.Series(dtype=float)
        return windowed.groupby("session_date")["close"].last()

    return windowed.groupby("session_date")["close"].last()


def compute_symbol_scan_frame(
    symbol: str,
    minute_df: pd.DataFrame,
    cfg: ScannerConfig,
) -> pd.DataFrame:
    """Build per-session scanner metrics for one symbol."""
    or_volume = _opening_range_volume(minute_df, cfg.opening_range_minutes)
    if or_volume.empty:
        return pd.DataFrame()

    price_at_or = _price_at_or_end(minute_df, cfg.opening_range_minutes)
    daily = build_daily_context(regular_session_only(minute_df))

    frame = pd.DataFrame({"session_date": or_volume.index, "or_volume": or_volume.values})
    frame["symbol"] = symbol.upper()
    frame["price_at_or"] = frame["session_date"].map(price_at_or)
    if not daily.empty:
        daily_map = daily.set_index("session_date")
        frame["prev_close"] = frame["session_date"].map(daily_map.get("prev_close", pd.Series()))
        frame["atr_d_pct"] = frame["session_date"].map(daily_map.get("atr_d_pct", pd.Series()))
        frame["gap_pct"] = frame["session_date"].map(
            lambda d: (
                (daily_map.loc[d, "session_open"] - daily_map.loc[d, "prev_close"])
                / daily_map.loc[d, "prev_close"]
                if d in daily_map.index
                and pd.notna(daily_map.loc[d, "prev_close"])
                and daily_map.loc[d, "prev_close"] != 0
                else pd.NA
            )
        )
    else:
        frame["prev_close"] = pd.NA
        frame["atr_d_pct"] = pd.NA
        frame["gap_pct"] = pd.NA

    history = frame.sort_values("session_date")
    min_periods = min(5, cfg.rvol_lookback_days)
    history["trailing_or_avg"] = history["or_volume"].shift(1).rolling(
        cfg.rvol_lookback_days, min_periods=min_periods
    ).mean()
    history["opening_rvol"] = history["or_volume"] / history["trailing_or_avg"]
    return history.reset_index(drop=True)


def _passes_scanner_filters(row: pd.Series, cfg: ScannerConfig) -> bool:
    price = row.get("price_at_or")
    opening_rvol = row.get("opening_rvol")
    atr_d_pct = row.get("atr_d_pct")
    if pd.isna(price) or float(price) < cfg.min_price:
        return False
    if pd.isna(opening_rvol) or float(opening_rvol) < cfg.min_opening_rvol:
        return False
    if pd.notna(atr_d_pct) and float(atr_d_pct) < cfg.min_atr_d_pct:
        return False
    return True


def build_daily_selections(
    symbol_data: dict[str, pd.DataFrame],
    cfg: ScannerConfig | None = None,
) -> dict[date, list[str]]:
    """Rank all symbols each session and return top-N 'in play' picks."""
    cfg = cfg or scanner_config_from_env()
    day_rows: list[pd.DataFrame] = []

    for symbol, minute_df in symbol_data.items():
        metrics = compute_symbol_scan_frame(symbol, minute_df, cfg)
        if metrics.empty:
            continue
        day_rows.append(metrics)

    if not day_rows:
        return {}

    combined = pd.concat(day_rows, ignore_index=True)
    selections: dict[date, list[str]] = {}

    for session_date, group in combined.groupby("session_date"):
        filtered = group[group.apply(lambda row: _passes_scanner_filters(row, cfg), axis=1)]
        if filtered.empty:
            continue
        ranked = filtered.sort_values("opening_rvol", ascending=False)
        top = ranked.head(cfg.top_n)["symbol"].tolist()
        selections[session_date] = top

    return selections


def build_scanner_backtest_context(
    data_dir: str,
    start_date: str,
    end_date: str,
    candidates: list[str] | None = None,
    cfg: ScannerConfig | None = None,
    market_filter_symbols: list[str] | None = None,
) -> dict[str, Any]:
    """Load candidate pool, compute daily selections, return replay inputs."""
    cfg = cfg or scanner_config_from_env()
    market_filter_symbols = market_filter_symbols or ["SPY", "QQQ"]
    trade_pool = resolve_available_candidates(data_dir, candidates)
    if not trade_pool:
        raise ValueError(f"No scanner candidate CSVs found in {data_dir}")

    load_symbols = list(dict.fromkeys(trade_pool + market_filter_symbols))
    symbol_data = load_symbol_data(load_symbols, data_dir, start_date, end_date)
    trade_data = {symbol: symbol_data[symbol] for symbol in trade_pool if symbol in symbol_data}
    daily_selections = build_daily_selections(trade_data, cfg)

    return {
        "trade_pool": trade_pool,
        "daily_selections": daily_selections,
        "market_filter_symbols": market_filter_symbols,
        "loaded_symbols": sorted(trade_data.keys()),
        "selection_days": len(daily_selections),
        "avg_symbols_per_day": (
            sum(len(v) for v in daily_selections.values()) / len(daily_selections)
            if daily_selections
            else 0.0
        ),
        "config": cfg,
    }


def save_daily_selections(
    daily_selections: dict[date, list[str]],
    output_dir: str,
    run_id: str,
) -> str:
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    rows = []
    for session_date, symbols in sorted(daily_selections.items()):
        for rank, symbol in enumerate(symbols, start=1):
            rows.append(
                {
                    "session_date": session_date.isoformat(),
                    "rank": rank,
                    "symbol": symbol,
                }
            )
    path = Path(output_dir) / f"{run_id}_daily_selections.csv"
    pd.DataFrame(rows).to_csv(path, index=False)

    summary_path = Path(output_dir) / f"{run_id}_summary.json"
    with open(summary_path, "w", encoding="utf-8") as file:
        json.dump(
            {
                "selection_days": len(daily_selections),
                "avg_symbols_per_day": (
                    sum(len(v) for v in daily_selections.values()) / len(daily_selections)
                    if daily_selections
                    else 0.0
                ),
                "csv_path": str(path),
            },
            file,
            indent=2,
        )
    return str(path)


def selection_summary_for_date(daily_selections: dict[date, list[str]], session_date: date) -> list[str]:
    return list(daily_selections.get(session_date, []))
