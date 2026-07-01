from __future__ import annotations

import math

import pandas as pd


def analyze_risk_reward(trade_rows: list[dict]) -> dict:
    if not trade_rows:
        return {
            "average_risk_per_trade": None,
            "average_reward_per_trade": None,
            "average_r_multiple": None,
            "reward_to_risk_ratio": None,
            "loss_distribution": {},
            "win_distribution": {},
            "stop_loss_hit_rate": None,
            "take_profit_hit_rate": None,
            "breakeven_win_rate": None,
            "current_win_rate_clears_breakeven": None,
            "payoff_profile": "not available: no closed trades",
            "explanation": "Risk/reward analysis needs closed trades with entry, exit, and stop data.",
        }

    data = pd.DataFrame(trade_rows).copy()
    data["pnl_dollars"] = pd.to_numeric(data.get("pnl_dollars"), errors="coerce")
    data["entry_price"] = pd.to_numeric(data.get("entry_price"), errors="coerce")
    data["exit_price"] = pd.to_numeric(data.get("exit_price"), errors="coerce")
    data["position_size"] = pd.to_numeric(data.get("position_size"), errors="coerce")
    data["stop_loss"] = pd.to_numeric(data.get("stop_loss"), errors="coerce")
    data["take_profit"] = pd.to_numeric(data.get("take_profit"), errors="coerce")

    risk_per_share = (data["entry_price"] - data["stop_loss"]).where(data["stop_loss"].notna())
    reward_per_share = (data["take_profit"] - data["entry_price"]).where(data["take_profit"].notna())
    risk_dollars = (risk_per_share * data["position_size"]).where(risk_per_share > 0)
    reward_dollars = (reward_per_share * data["position_size"]).where(reward_per_share > 0)
    r_multiple = (data["pnl_dollars"] / risk_dollars).where(risk_dollars > 0)

    wins = data[data["pnl_dollars"] > 0]
    losses = data[data["pnl_dollars"] <= 0]
    avg_win = float(wins["pnl_dollars"].mean()) if not wins.empty else 0.0
    avg_loss_abs = abs(float(losses["pnl_dollars"].mean())) if not losses.empty else 0.0
    breakeven = avg_loss_abs / (avg_win + avg_loss_abs) if (avg_win + avg_loss_abs) > 0 else None
    win_rate = len(wins) / len(data) if len(data) else None

    stop_hit_rate = _reason_rate(data, ["stop"])
    target_hit_rate = _reason_rate(data, ["take profit", "target"])
    payoff_profile = _payoff_profile(data)

    return {
        "average_risk_per_trade": _mean_or_none(risk_dollars),
        "average_reward_per_trade": _mean_or_none(reward_dollars),
        "average_r_multiple": _mean_or_none(r_multiple),
        "reward_to_risk_ratio": _safe_ratio(_mean_or_none(reward_dollars), _mean_or_none(risk_dollars)),
        "loss_distribution": _distribution(losses["pnl_dollars"].abs() if not losses.empty else pd.Series(dtype=float)),
        "win_distribution": _distribution(wins["pnl_dollars"] if not wins.empty else pd.Series(dtype=float)),
        "stop_loss_hit_rate": stop_hit_rate,
        "take_profit_hit_rate": target_hit_rate,
        "breakeven_win_rate": breakeven,
        "current_win_rate_clears_breakeven": None if breakeven is None else bool(win_rate >= breakeven),
        "payoff_profile": payoff_profile,
        "explanation": _explain(payoff_profile, win_rate, breakeven, _mean_or_none(r_multiple)),
    }


def _distribution(series: pd.Series) -> dict:
    clean = pd.to_numeric(series, errors="coerce").dropna()
    if clean.empty:
        return {}
    return {
        "min": float(clean.min()),
        "median": float(clean.median()),
        "mean": float(clean.mean()),
        "max": float(clean.max()),
    }


def _reason_rate(data: pd.DataFrame, needles: list[str]) -> float:
    if data.empty or "exit_reason" not in data:
        return 0.0
    reasons = data["exit_reason"].fillna("").astype(str).str.lower()
    matches = reasons.apply(lambda value: any(needle in value for needle in needles))
    return float(matches.mean())


def _payoff_profile(data: pd.DataFrame) -> str:
    wins = data[data["pnl_dollars"] > 0]["pnl_dollars"]
    losses = data[data["pnl_dollars"] <= 0]["pnl_dollars"].abs()
    if wins.empty:
        return "no winning trades observed"
    if losses.empty:
        return "no losing trades observed"
    top_win_share = float(wins.nlargest(max(1, math.ceil(len(wins) * 0.2))).sum() / wins.sum())
    avg_win = float(wins.mean())
    avg_loss = float(losses.mean())
    if top_win_share > 0.65:
        return "profits rely on a small number of outsized winners"
    if avg_win < avg_loss:
        return "many small wins must overcome larger average losses"
    return "balanced payoff profile"


def _explain(profile: str, win_rate: float | None, breakeven: float | None, avg_r: float | None) -> str:
    parts = [profile.rstrip(".") + "."]
    if breakeven is not None and win_rate is not None:
        parts.append(
            f"Observed win rate is {win_rate * 100:.1f}% versus an estimated breakeven rate of {breakeven * 100:.1f}%."
        )
    if avg_r is not None:
        parts.append(f"Average R multiple is {avg_r:.2f}.")
    return " ".join(parts)


def _mean_or_none(series: pd.Series) -> float | None:
    clean = pd.to_numeric(series, errors="coerce").dropna()
    if clean.empty:
        return None
    return float(clean.mean())


def _safe_ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator in {None, 0}:
        return None
    return float(numerator / denominator)
