from __future__ import annotations

import csv
import json
import math
import os
from datetime import datetime, timezone
from uuid import uuid4

import pandas as pd


LEADERBOARD_FIELDS = [
    "rank",
    "strategy_name",
    "status",
    "recommendation",
    "score",
    "closed_trades",
    "total_return",
    "profit_factor",
    "expectancy",
    "win_rate",
    "max_drawdown",
    "best_regimes",
    "avoid_regimes",
    "report_path",
]


def build_multi_strategy_report(
    *,
    reports: list[dict],
    skipped: list[dict],
    start_date: str,
    end_date: str,
    profile: str,
    symbols_by_strategy: dict[str, list[str]],
    market_filters_by_strategy: dict[str, list[str]],
) -> dict:
    rows = [_leaderboard_row(report) for report in reports]
    ranked_rows = sorted(rows, key=lambda row: row["score"], reverse=True)
    for index, row in enumerate(ranked_rows, start=1):
        row["rank"] = index

    return _json_safe(
        {
            "run_id": f"multi_strategy_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid4().hex[:8]}",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "profile": profile,
            "start_date": start_date,
            "end_date": end_date,
            "mode": "RESEARCH_ONLY",
            "summary": _summary(ranked_rows, skipped),
            "leaderboard": ranked_rows,
            "best_by_regime": _best_by_regime(reports),
            "strategy_allocator": _allocator_guidance(ranked_rows),
            "symbols_by_strategy": symbols_by_strategy,
            "market_filters_by_strategy": market_filters_by_strategy,
            "skipped": skipped,
            "reports": reports,
        }
    )


def save_multi_strategy_report(report: dict, output_dir: str = "research_results/multi_strategy") -> dict:
    os.makedirs(output_dir, exist_ok=True)
    run_id = report["run_id"]
    json_path = os.path.join(output_dir, f"{run_id}.json")
    leaderboard_path = os.path.join(output_dir, "multi_strategy_leaderboard.csv")
    latest_path = os.path.join(output_dir, "latest_multi_strategy_report.json")

    with open(json_path, "w", encoding="utf-8") as file:
        json.dump(report, file, indent=2)
    with open(latest_path, "w", encoding="utf-8") as file:
        json.dump(report, file, indent=2)
    _write_leaderboard(leaderboard_path, report.get("leaderboard", []))
    return {
        "json_path": json_path,
        "latest_path": latest_path,
        "leaderboard_path": leaderboard_path,
    }


def _leaderboard_row(report: dict) -> dict:
    backtest = report.get("backtest", {})
    gate = report.get("validation_gate", {})
    regime = report.get("market_regime", {})
    recommendation = report.get("promotion_recommendation", {}).get("recommendation", "Keep RESEARCH_ONLY")
    score = _strategy_score(report)
    best_regimes = [
        row.get("name")
        for row in regime.get("performance_by_regime", [])
        if row.get("expectancy") is not None and float(row.get("expectancy", 0.0)) > 0
    ][:3]
    avoid_regimes = [
        row.get("name")
        for row in regime.get("performance_by_regime", [])
        if row.get("expectancy") is not None and float(row.get("expectancy", 0.0)) < 0
    ]
    return {
        "rank": None,
        "strategy_name": report.get("strategy_name"),
        "status": report.get("status"),
        "recommendation": recommendation,
        "score": score,
        "closed_trades": int(backtest.get("closed_trades", 0) or 0),
        "total_return": _float_or_none(backtest.get("total_return")),
        "profit_factor": _finite_float(backtest.get("profit_factor")),
        "expectancy": _float_or_none(backtest.get("expectancy")),
        "win_rate": _float_or_none(backtest.get("win_rate")),
        "max_drawdown": _float_or_none(backtest.get("max_drawdown")),
        "passes_gate": bool(gate.get("passes", False)),
        "best_regimes": best_regimes,
        "avoid_regimes": avoid_regimes,
        "report_path": report.get("_report_path"),
    }


def _strategy_score(report: dict) -> float:
    backtest = report.get("backtest", {})
    closed_trades = int(backtest.get("closed_trades", 0) or 0)
    profit_factor = _finite_float(backtest.get("profit_factor")) or 0.0
    expectancy = _float_or_none(backtest.get("expectancy")) or 0.0
    total_return = _float_or_none(backtest.get("total_return")) or 0.0
    max_drawdown = abs(_float_or_none(backtest.get("max_drawdown")) or 0.0)
    win_rate = _float_or_none(backtest.get("win_rate")) or 0.0

    sample_factor = min(1.0, closed_trades / 30.0)
    pf_component = min(3.0, profit_factor) * 25.0
    expectancy_component = max(-50.0, min(50.0, expectancy)) * 0.8
    return_component = max(-0.5, min(0.5, total_return)) * 60.0
    drawdown_penalty = max_drawdown * 120.0
    win_component = win_rate * 10.0
    no_sample_penalty = 30.0 if closed_trades == 0 else 0.0
    return round(
        (pf_component + expectancy_component + return_component + win_component) * sample_factor
        - drawdown_penalty
        - no_sample_penalty,
        4,
    )


def _best_by_regime(reports: list[dict]) -> list[dict]:
    candidates: dict[str, list[dict]] = {}
    for report in reports:
        strategy_name = report.get("strategy_name")
        for row in report.get("market_regime", {}).get("performance_by_regime", []):
            regime = str(row.get("name"))
            if not regime or regime == "nan":
                continue
            candidates.setdefault(regime, []).append(
                {
                    "strategy_name": strategy_name,
                    "closed_trades": int(row.get("closed_trades", 0) or 0),
                    "expectancy": _float_or_none(row.get("expectancy")) or 0.0,
                    "win_rate": _float_or_none(row.get("win_rate")),
                    "total_pnl": _float_or_none(row.get("total_pnl")) or 0.0,
                }
            )

    results = []
    for regime, rows in candidates.items():
        ranked = sorted(
            rows,
            key=lambda item: (item["expectancy"], item["total_pnl"], item["closed_trades"]),
            reverse=True,
        )
        best = ranked[0]
        results.append(
            {
                "regime": regime,
                "recommended_strategy": best["strategy_name"] if best["expectancy"] > 0 and best["closed_trades"] >= 3 else None,
                "reason": _regime_reason(best),
                "candidates": ranked,
            }
        )
    return sorted(results, key=lambda item: item["regime"])


def _allocator_guidance(leaderboard: list[dict]) -> dict:
    if not leaderboard:
        return {
            "mode": "NO_TRADE",
            "selected_strategy": None,
            "reason": "No runnable strategies produced a report.",
        }

    leader = leaderboard[0]
    if leader["closed_trades"] < 30:
        mode = "SHADOW_ONLY"
        reason = "Top strategy does not have enough sample size for allocation."
    elif leader["expectancy"] is None or leader["expectancy"] <= 0:
        mode = "NO_TRADE"
        reason = "Top strategy expectancy is not positive."
    elif leader["profit_factor"] is None or leader["profit_factor"] < 1.1:
        mode = "SHADOW_ONLY"
        reason = "Top strategy profit factor is too weak for allocation."
    else:
        mode = "PAPER_CANDIDATE"
        reason = "Top strategy has positive expectancy and acceptable profit factor in this sample."

    return {
        "mode": mode,
        "selected_strategy": leader["strategy_name"] if mode == "PAPER_CANDIDATE" else None,
        "leader": leader,
        "reason": reason,
        "next_step": "Run all candidates in shadow mode and keep comparing by regime before any live routing.",
    }


def _summary(leaderboard: list[dict], skipped: list[dict]) -> dict:
    leader = leaderboard[0] if leaderboard else None
    return {
        "strategies_tested": len(leaderboard),
        "strategies_skipped": len(skipped),
        "top_strategy": leader.get("strategy_name") if leader else None,
        "top_score": leader.get("score") if leader else None,
        "message": "Research-only multi-strategy comparison. This does not change ACTIVE_STRATEGY or place trades.",
    }


def _regime_reason(row: dict) -> str:
    if row["expectancy"] <= 0:
        return "No strategy has positive expectancy in this regime sample."
    if row["closed_trades"] < 3:
        return "Positive expectancy but too few trades to trust yet."
    return f"Best expectancy in sample: ${row['expectancy']:.2f} across {row['closed_trades']} trades."


def _write_leaderboard(path: str, rows: list[dict]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=LEADERBOARD_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    key: _csv_value(row.get(key))
                    for key in LEADERBOARD_FIELDS
                }
            )


def _csv_value(value):
    if isinstance(value, list):
        return ",".join(str(item) for item in value)
    return value


def _finite_float(value) -> float | None:
    number = _float_or_none(value)
    if number is None or math.isinf(number) or math.isnan(number):
        return None
    return number


def _float_or_none(value) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _json_safe(value):
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value
