from __future__ import annotations

import math
from zoneinfo import ZoneInfo

import pandas as pd


EASTERN = ZoneInfo("America/New_York")


def build_strategy_scorecard(trade_rows: list[dict]) -> dict:
    if not trade_rows:
        return {
            "by_symbol": [],
            "by_entry_hour": [],
            "by_exit_reason": [],
            "recommendations": ["No closed trades available for scorecard analysis."],
        }

    data = pd.DataFrame(trade_rows)
    data["entry_hour_et"] = (
        data["entry_timestamp"]
        .dt.tz_convert(EASTERN)
        .dt.strftime("%H:00 ET")
    )
    scorecard = {
        "by_symbol": _group_scorecard(data, "ticker"),
        "by_entry_hour": _group_scorecard(data, "entry_hour_et"),
        "by_exit_reason": _group_scorecard(data, "exit_reason"),
    }
    scorecard["recommendations"] = _recommendations(scorecard)
    return scorecard


def print_strategy_scorecard(scorecard: dict, limit: int = 8) -> None:
    print("\nSTRATEGY SCORECARD")
    print("------------------")
    _print_group("By symbol", scorecard.get("by_symbol", []), limit)
    _print_group("By entry hour", scorecard.get("by_entry_hour", []), limit)
    _print_group("By exit reason", scorecard.get("by_exit_reason", []), limit)

    if scorecard.get("recommendations"):
        print("\nRecommended next cuts:")
        for item in scorecard["recommendations"]:
            print(f"- {item}")


def _group_scorecard(data: pd.DataFrame, column: str) -> list[dict]:
    rows = []
    for value, group in data.groupby(column, dropna=False):
        pnl = group["pnl_dollars"].astype(float)
        wins = pnl[pnl > 0]
        losses = pnl[pnl <= 0]
        gross_profit = float(wins.sum()) if not wins.empty else 0.0
        gross_loss = abs(float(losses.sum())) if not losses.empty else 0.0
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else math.inf
        rows.append(
            {
                "value": str(value),
                "closed_trades": int(len(group)),
                "win_rate": float((pnl > 0).mean()),
                "profit_factor": profit_factor,
                "expectancy": float(pnl.mean()),
                "total_pnl": float(pnl.sum()),
            }
        )
    return sorted(rows, key=lambda item: item["total_pnl"])


def _recommendations(scorecard: dict) -> list[str]:
    recommendations = []
    for row in scorecard.get("by_symbol", []):
        if row["closed_trades"] >= 5 and row["expectancy"] < 0:
            recommendations.append(
                f"Review or exclude {row['value']}: {row['closed_trades']} trades, "
                f"expectancy ${row['expectancy']:.2f}, total P/L ${row['total_pnl']:.2f}."
            )
    for row in scorecard.get("by_entry_hour", []):
        if row["closed_trades"] >= 5 and row["expectancy"] < 0:
            recommendations.append(
                f"Review entry hour {row['value']}: {row['closed_trades']} trades, "
                f"expectancy ${row['expectancy']:.2f}."
            )
    return recommendations[:6] or ["No obvious high-sample negative bucket found."]


def _print_group(title: str, rows: list[dict], limit: int) -> None:
    if not rows:
        return
    print(f"\n{title}:")
    for row in rows[:limit]:
        profit_factor = row["profit_factor"]
        profit_factor_text = "inf" if math.isinf(profit_factor) else f"{profit_factor:.2f}"
        print(
            f"  {row['value']}: trades={row['closed_trades']} "
            f"win={row['win_rate'] * 100:.1f}% pf={profit_factor_text} "
            f"exp=${row['expectancy']:.2f} pnl=${row['total_pnl']:.2f}"
        )
