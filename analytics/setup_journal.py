from __future__ import annotations

import math
from collections import defaultdict
from typing import Iterable

import pandas as pd


JOURNAL_COLUMNS = [
    "run_id",
    "symbol",
    "strategy_name",
    "setup_type",
    "entry_timestamp",
    "exit_timestamp",
    "entry_price",
    "exit_price",
    "position_size",
    "stop_loss",
    "take_profit",
    "risk_dollars",
    "reward_dollars",
    "risk_reward",
    "pnl_dollars",
    "pnl_percent",
    "outcome",
    "setup_quality",
    "hold_time_minutes",
    "market_regime",
    "ema_trend",
    "rsi",
    "rvol",
    "atr",
    "vwap_position",
    "spread",
    "volume",
    "entry_reason",
    "exit_reason",
]

SUMMARY_COLUMNS = [
    "strategy_name",
    "setup_type",
    "market_regime",
    "setup_quality",
    "closed_trades",
    "win_rate",
    "profit_factor",
    "expectancy",
    "total_pnl",
    "average_winner",
    "average_loser",
    "average_risk_reward",
    "average_hold_minutes",
    "top_exit_reason",
]


def build_setup_journal(
    trade_rows: Iterable[dict],
    run_id: int | None = None,
    config_overrides: dict | None = None,
) -> list[dict]:
    journal_rows = []

    for trade in trade_rows:
        entry_price = _float_or_none(trade.get("entry_price"))
        exit_price = _float_or_none(trade.get("exit_price"))
        shares = int(trade.get("position_size") or 0)
        stop_loss = _float_or_none(trade.get("stop_loss"))
        take_profit = _float_or_none(trade.get("take_profit"))
        pnl_dollars = _float_or_zero(trade.get("pnl_dollars"))
        risk_per_share = _risk_per_share(entry_price, stop_loss)
        reward_per_share = _reward_per_share(entry_price, take_profit)
        risk_reward = _risk_reward(risk_per_share, reward_per_share)

        row = {
            "run_id": run_id,
            "symbol": trade.get("ticker"),
            "strategy_name": trade.get("strategy_name"),
            "setup_type": trade.get("setup_type"),
            "entry_timestamp": trade.get("entry_timestamp"),
            "exit_timestamp": trade.get("exit_timestamp"),
            "entry_price": entry_price,
            "exit_price": exit_price,
            "position_size": shares,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "risk_dollars": risk_per_share * shares if risk_per_share is not None else None,
            "reward_dollars": reward_per_share * shares if reward_per_share is not None else None,
            "risk_reward": risk_reward,
            "pnl_dollars": pnl_dollars,
            "pnl_percent": _float_or_zero(trade.get("pnl_percent")),
            "outcome": "WIN" if pnl_dollars > 0 else "LOSS",
            "setup_quality": classify_setup_quality(trade),
            "hold_time_minutes": _float_or_zero(trade.get("hold_time_minutes")),
            "market_regime": trade.get("spy_trend"),
            "ema_trend": trade.get("ema_trend"),
            "rsi": _float_or_none(trade.get("rsi")),
            "rvol": _float_or_none(trade.get("rvol")),
            "atr": _float_or_none(trade.get("atr")),
            "vwap_position": _float_or_none(trade.get("vwap_position")),
            "spread": _float_or_none(trade.get("spread")),
            "volume": _float_or_none(trade.get("volume")),
            "entry_reason": trade.get("entry_reason"),
            "exit_reason": trade.get("exit_reason"),
        }

        if config_overrides:
            row.update({f"config_{key}": value for key, value in config_overrides.items()})

        journal_rows.append(row)

    return journal_rows


def classify_setup_quality(trade: dict) -> str:
    pnl_dollars = _float_or_zero(trade.get("pnl_dollars"))
    exit_reason = str(trade.get("exit_reason") or "").lower()

    if pnl_dollars > 0:
        if "take profit" in exit_reason or "target" in exit_reason:
            return "GOOD_SETUP_GOOD_OUTCOME"
        return "WORKED_BUT_REVIEW"

    if "stop" in exit_reason or "lost vwap" in exit_reason or "regime flip" in exit_reason:
        return "BAD_SETUP_BAD_OUTCOME"

    return "FAILED_OR_UNCLEAR"


def summarize_setup_journal(journal_rows: Iterable[dict]) -> list[dict]:
    data = pd.DataFrame(list(journal_rows))

    if data.empty:
        return []

    group_columns = ["strategy_name", "setup_type", "market_regime", "setup_quality"]
    summaries = []

    for keys, group in data.groupby(group_columns, dropna=False):
        pnl = group["pnl_dollars"].astype(float)
        wins = pnl[pnl > 0]
        losses = pnl[pnl <= 0]
        gross_profit = float(wins.sum()) if not wins.empty else 0.0
        gross_loss = abs(float(losses.sum())) if not losses.empty else 0.0
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else math.inf

        summaries.append({
            "strategy_name": keys[0],
            "setup_type": keys[1],
            "market_regime": keys[2],
            "setup_quality": keys[3],
            "closed_trades": int(len(group)),
            "win_rate": float((pnl > 0).mean()),
            "profit_factor": profit_factor,
            "expectancy": float(pnl.mean()),
            "total_pnl": float(pnl.sum()),
            "average_winner": float(wins.mean()) if not wins.empty else 0.0,
            "average_loser": float(losses.mean()) if not losses.empty else 0.0,
            "average_risk_reward": _mean_or_none(group["risk_reward"]),
            "average_hold_minutes": float(group["hold_time_minutes"].astype(float).mean()),
            "top_exit_reason": _top_value(group["exit_reason"]),
        })

    return summaries


def summarize_by_run(journal_rows: Iterable[dict]) -> dict[int, dict]:
    data = pd.DataFrame(list(journal_rows))

    if data.empty or "run_id" not in data:
        return {}

    summaries = {}

    for run_id, group in data.groupby("run_id", dropna=True):
        quality_counts = defaultdict(int)
        for value in group["setup_quality"]:
            quality_counts[str(value)] += 1

        summaries[int(run_id)] = {
            "good_setup_good_outcome": quality_counts["GOOD_SETUP_GOOD_OUTCOME"],
            "bad_setup_bad_outcome": quality_counts["BAD_SETUP_BAD_OUTCOME"],
            "worked_but_review": quality_counts["WORKED_BUT_REVIEW"],
            "failed_or_unclear": quality_counts["FAILED_OR_UNCLEAR"],
        }

    return summaries


def _risk_per_share(entry_price: float | None, stop_loss: float | None) -> float | None:
    if entry_price is None or stop_loss is None:
        return None
    return max(0.0, entry_price - stop_loss)


def _reward_per_share(entry_price: float | None, take_profit: float | None) -> float | None:
    if entry_price is None or take_profit is None:
        return None
    return max(0.0, take_profit - entry_price)


def _risk_reward(risk_per_share: float | None, reward_per_share: float | None) -> float | None:
    if risk_per_share is None or reward_per_share is None or risk_per_share <= 0:
        return None
    return reward_per_share / risk_per_share


def _float_or_none(value) -> float | None:
    if value is None or value == "":
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(numeric):
        return None
    return numeric


def _float_or_zero(value) -> float:
    numeric = _float_or_none(value)
    return 0.0 if numeric is None else numeric


def _mean_or_none(series) -> float | None:
    numeric = pd.to_numeric(series, errors="coerce").dropna()
    if numeric.empty:
        return None
    return float(numeric.mean())


def _top_value(series):
    counts = series.dropna().value_counts()
    if counts.empty:
        return None
    return counts.index[0]
