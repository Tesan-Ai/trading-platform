from __future__ import annotations

import math
from dataclasses import dataclass

import pandas as pd
from zoneinfo import ZoneInfo

EASTERN = ZoneInfo("America/New_York")


@dataclass
class BucketSpec:
    column: str
    name: str
    bins: list[float] | None = None
    labels: list[str] | None = None


def build_strategy_diagnostics(
    trade_rows: list[dict],
    equity_curve: list[dict],
    signal_rows: list[dict] | None = None,
) -> dict:
    data = pd.DataFrame(trade_rows)
    if data.empty:
        return {
            "overall": _overall_metrics(data, equity_curve, signal_rows),
            "breakdowns": {},
            "improvement_candidates": [
                {
                    "severity": "warning",
                    "category": "sample_size",
                    "finding": "No closed trades were available.",
                    "recommendation": "Collect more paper/backtest trades before changing strategy rules.",
                }
            ],
        }

    enriched = _add_derived_columns(data)
    breakdowns = {
        "by_symbol": _group_metrics(enriched, "ticker"),
        "by_day": _group_metrics(enriched, "entry_day"),
        "by_time_bucket": _group_metrics(enriched, "entry_time_bucket"),
        "by_entry_time": _group_metrics(enriched, "entry_time"),
        "by_volume_ratio_bucket": _group_metrics(enriched, "volume_ratio_bucket"),
        "by_spread_bucket": _group_metrics(enriched, "spread_bucket"),
        "by_atr_extension_bucket": _group_metrics(enriched, "atr_extension_bucket"),
        "by_market_filter_state": _group_metrics(enriched, "market_filter_state"),
        "by_qqq_vwap": _group_metrics(enriched, "qqq_vwap_state"),
        "by_spy_vwap": _group_metrics(enriched, "spy_vwap_state"),
        "by_opening_range_size_bucket": _group_metrics(enriched, "opening_range_size_bucket"),
        "by_exit_reason": _group_metrics(enriched, "exit_reason"),
        "by_stop_type": _group_metrics(enriched, "selected_stop_method"),
        "by_trade_number_of_day": _group_metrics(enriched, "trade_number_of_day"),
    }
    diagnostics = {
        "overall": _overall_metrics(enriched, equity_curve, signal_rows),
        "breakdowns": breakdowns,
        "improvement_candidates": build_improvement_candidates(breakdowns, enriched),
    }
    return diagnostics


def build_improvement_candidates(breakdowns: dict, data: pd.DataFrame) -> list[dict]:
    candidates: list[dict] = []

    for row in breakdowns.get("by_symbol", []):
        if row["closed_trades"] >= 3 and row["expectancy"] < 0 and row["profit_factor"] < 1:
            candidates.append(
                _candidate(
                    "high",
                    "symbol_filter",
                    f"{row['bucket']} is dragging performance.",
                    f"Research disabling or separately filtering {row['bucket']}; do not remove permanently without out-of-sample confirmation.",
                    row,
                )
            )

    for row in breakdowns.get("by_time_bucket", []):
        if row["closed_trades"] >= 3 and row["expectancy"] < 0:
            candidates.append(
                _candidate(
                    "medium",
                    "entry_window",
                    f"Time bucket {row['bucket']} has negative expectancy.",
                    "Test an earlier entry-window cutoff and compare validation results.",
                    row,
                )
            )

    low_volume = _find_bucket(breakdowns.get("by_volume_ratio_bucket", []), contains="<2")
    if low_volume and low_volume["closed_trades"] >= 3 and low_volume["expectancy"] < 0:
        candidates.append(
            _candidate(
                "medium",
                "volume_filter",
                "Lower-volume setups are underperforming.",
                "Test raising minimum volume ratio to 2.0 or 2.2.",
                low_volume,
            )
        )

    for row in breakdowns.get("by_atr_extension_bucket", []):
        if row["closed_trades"] >= 3 and ">" in str(row["bucket"]) and row["expectancy"] < 0:
            candidates.append(
                _candidate(
                    "medium",
                    "vwap_extension",
                    f"Extended entries in {row['bucket']} are losing.",
                    "Test a lower max ATR extension from VWAP.",
                    row,
                )
            )

    for row in breakdowns.get("by_stop_type", []):
        if row["closed_trades"] >= 3 and row["expectancy"] < 0:
            candidates.append(
                _candidate(
                    "medium",
                    "stop_type",
                    f"Stop type {row['bucket']} has negative expectancy.",
                    "Review whether this stop method is too wide, too tight, or selected in weak setups.",
                    row,
                )
            )

    for row in breakdowns.get("by_exit_reason", []):
        bucket = str(row["bucket"]).lower()
        if row["closed_trades"] >= 3 and row["expectancy"] < 0 and ("max hold" in bucket or "force" in bucket):
            candidates.append(
                _candidate(
                    "medium",
                    "exit_timing",
                    f"{row['bucket']} exits are unprofitable.",
                    "Test a time stop or earlier exit rule in paper/backtest only.",
                    row,
                )
            )

    for row in breakdowns.get("by_trade_number_of_day", []):
        if row["closed_trades"] >= 3 and int(float(row["bucket"])) > 1 and row["expectancy"] < 0:
            candidates.append(
                _candidate(
                    "medium",
                    "overtrading",
                    f"Trade number {row['bucket']} of the day has negative expectancy.",
                    "Test max 1 or max 2 trades per day.",
                    row,
                )
            )

    if len(data) < 100:
        candidates.append(
            _candidate(
                "warning",
                "sample_size",
                "Closed trade sample is small.",
                "Not enough sample size to trust optimization yet; use walk-forward validation and paper results.",
                {"closed_trades": int(len(data))},
            )
        )

    return candidates


def _overall_metrics(data: pd.DataFrame, equity_curve: list[dict], signal_rows: list[dict] | None) -> dict:
    starting_equity = float(equity_curve[0]["equity"]) if equity_curve else None
    ending_equity = float(equity_curve[-1]["equity"]) if equity_curve else None
    total_return = (
        (ending_equity - starting_equity) / starting_equity
        if starting_equity and ending_equity is not None
        else 0.0
    )
    skipped = 0
    blocked = 0
    if signal_rows:
        skipped = sum(1 for row in signal_rows if not row.get("entry_approved"))
        blocked = sum(1 for row in signal_rows if row.get("rejection_reason"))

    if data.empty:
        return {
            "starting_equity": starting_equity,
            "ending_equity": ending_equity,
            "total_return": total_return,
            "closed_trades": 0,
            "skipped_trades": skipped,
            "blocked_trades": blocked,
        }

    wins = data[data["pnl_dollars"] > 0]
    losses = data[data["pnl_dollars"] <= 0]
    gross_profit = float(wins["pnl_dollars"].sum()) if not wins.empty else 0.0
    gross_loss = abs(float(losses["pnl_dollars"].sum())) if not losses.empty else 0.0
    return {
        "starting_equity": starting_equity,
        "ending_equity": ending_equity,
        "total_return": total_return,
        "closed_trades": int(len(data)),
        "win_rate": float(len(wins) / len(data)),
        "profit_factor": gross_profit / gross_loss if gross_loss else math.inf,
        "expectancy": float(data["pnl_dollars"].mean()),
        "average_r": _mean(data, "r_multiple"),
        "average_winner": float(wins["pnl_dollars"].mean()) if not wins.empty else 0.0,
        "average_loser": float(losses["pnl_dollars"].mean()) if not losses.empty else 0.0,
        "largest_winner": float(wins["pnl_dollars"].max()) if not wins.empty else 0.0,
        "largest_loser": float(losses["pnl_dollars"].min()) if not losses.empty else 0.0,
        "max_drawdown": _max_drawdown(equity_curve),
        "average_hold_time": _mean(data, "hold_time_minutes"),
        "median_hold_time": float(data["hold_time_minutes"].median()) if "hold_time_minutes" in data else 0.0,
        "estimated_fees_slippage": 0.0,
        "skipped_trades": skipped,
        "blocked_trades": blocked,
    }


def _add_derived_columns(data: pd.DataFrame) -> pd.DataFrame:
    enriched = data.copy()
    timestamps = pd.to_datetime(enriched["entry_timestamp"])
    if getattr(timestamps.dt, "tz", None) is not None:
        timestamps = timestamps.dt.tz_convert(EASTERN)
    enriched["entry_day"] = timestamps.dt.day_name()
    enriched["entry_time"] = timestamps.dt.strftime("%H:%M")
    enriched["entry_time_bucket"] = pd.cut(
        timestamps.dt.hour * 60 + timestamps.dt.minute,
        bins=[0, 9 * 60 + 45, 10 * 60, 10 * 60 + 15, 10 * 60 + 30, 24 * 60],
        labels=["09:35-09:45", "09:45-10:00", "10:00-10:15", "10:15-10:30", "after_10:30"],
        include_lowest=True,
    ).astype(str)
    enriched["trade_number_of_day"] = enriched.groupby(timestamps.dt.date).cumcount() + 1
    enriched["volume_ratio_bucket"] = _cut(enriched, "rvol", [0, 2.0, 2.5, 3.0, 99], ["<2.0", "2.0-2.5", "2.5-3.0", ">3.0"])
    enriched["spread_bucket"] = _cut(enriched, "spread", [0, 0.05, 0.1, 0.15, 99], ["<=0.05", "0.05-0.10", "0.10-0.15", ">0.15"])
    enriched["atr_extension_bucket"] = _cut(enriched, "distance_from_vwap_atr", [-99, 0.5, 1.0, 1.5, 99], ["<=0.5", "0.5-1.0", "1.0-1.5", ">1.5"])
    enriched["opening_range_size_bucket"] = _cut(enriched, "opening_range_size", [0, 0.5, 1.0, 2.0, 99], ["<=0.5", "0.5-1.0", "1.0-2.0", ">2.0"])
    enriched["market_filter_state"] = enriched.get("spy_trend", "unknown")
    enriched["spy_vwap_state"] = enriched.get("spy_above_vwap_at_entry", pd.Series(["unknown"] * len(enriched))).map(_bool_label)
    enriched["qqq_vwap_state"] = enriched.get("qqq_above_vwap_at_entry", pd.Series(["unknown"] * len(enriched))).map(_bool_label)
    enriched["selected_stop_method"] = enriched.get("selected_stop_method", "unknown").fillna("unknown")
    return enriched


def _group_metrics(data: pd.DataFrame, column: str) -> list[dict]:
    if column not in data.columns:
        return []
    rows = []
    for bucket, group in data.groupby(column, dropna=False, observed=False):
        wins = group[group["pnl_dollars"] > 0]
        losses = group[group["pnl_dollars"] <= 0]
        gross_profit = float(wins["pnl_dollars"].sum()) if not wins.empty else 0.0
        gross_loss = abs(float(losses["pnl_dollars"].sum())) if not losses.empty else 0.0
        rows.append(
            {
                "bucket": str(bucket),
                "closed_trades": int(len(group)),
                "win_rate": float(len(wins) / len(group)) if len(group) else 0.0,
                "profit_factor": gross_profit / gross_loss if gross_loss else math.inf,
                "expectancy": float(group["pnl_dollars"].mean()),
                "average_r": _mean(group, "r_multiple"),
                "total_pnl": float(group["pnl_dollars"].sum()),
                "best_trade": float(group["pnl_dollars"].max()),
                "worst_trade": float(group["pnl_dollars"].min()),
            }
        )
    return sorted(rows, key=lambda item: item["total_pnl"])


def _candidate(severity: str, category: str, finding: str, recommendation: str, evidence: dict) -> dict:
    return {
        "severity": severity,
        "category": category,
        "finding": finding,
        "recommendation": recommendation,
        "evidence": evidence,
    }


def _cut(data: pd.DataFrame, column: str, bins: list[float], labels: list[str]):
    if column not in data.columns:
        return "unknown"
    return pd.cut(pd.to_numeric(data[column], errors="coerce"), bins=bins, labels=labels, include_lowest=True).astype(str)


def _bool_label(value) -> str:
    if value is True:
        return "above_vwap"
    if value is False:
        return "below_vwap"
    return "unknown"


def _find_bucket(rows: list[dict], contains: str) -> dict | None:
    for row in rows:
        if contains in str(row.get("bucket")):
            return row
    return None


def _mean(data: pd.DataFrame, column: str) -> float:
    if column not in data.columns:
        return 0.0
    series = pd.to_numeric(data[column], errors="coerce").dropna()
    if series.empty:
        return 0.0
    return float(series.mean())


def _max_drawdown(equity_curve: list[dict]) -> float:
    peak = None
    max_drawdown = 0.0
    for row in equity_curve or []:
        equity = float(row["equity"])
        peak = equity if peak is None else max(peak, equity)
        if peak:
            max_drawdown = max(max_drawdown, (peak - equity) / peak)
    return max_drawdown
