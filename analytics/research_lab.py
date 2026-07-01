from __future__ import annotations

import csv
import json
import math
import os
from datetime import datetime, timezone
from uuid import uuid4

import pandas as pd

import config
from analytics.drawdown import analyze_drawdowns
from analytics.monte_carlo import run_monte_carlo
from analytics.risk_reward import analyze_risk_reward
from analytics.trade_analytics import calculate_report
from validation.performance_gate import evaluate_validation_gate


SUMMARY_FIELDS = [
    "run_id",
    "created_at",
    "strategy",
    "profile",
    "status",
    "passes_gate",
    "start_date",
    "end_date",
    "symbols",
    "closed_trades",
    "total_return",
    "profit_factor",
    "expectancy",
    "win_rate",
    "max_drawdown",
    "monte_carlo_probability_of_loss",
    "recommendation",
    "json_path",
    "markdown_path",
]


def build_research_lab_report(
    *,
    strategy_name: str,
    profile: str,
    start_date: str,
    end_date: str,
    symbols: list[str],
    market_filters: list[str],
    starting_equity: float,
    trade_rows: list[dict],
    equity_curve: list[dict],
    base_report: dict | None = None,
    monte_carlo_runs: int = 1000,
) -> dict:
    trade_rows = _normalize_trade_rows(trade_rows)
    base_report = dict(base_report or calculate_report(trade_rows, equity_curve))
    enriched = _enrich_backtest_report(base_report, trade_rows, equity_curve, starting_equity, start_date, end_date)
    gate = evaluate_validation_gate(enriched, stage="backtest")
    risk_reward = analyze_risk_reward(trade_rows)
    drawdown = analyze_drawdowns(equity_curve, trade_rows)
    monte_carlo = run_monte_carlo(
        trade_rows,
        starting_equity,
        runs=monte_carlo_runs,
        max_drawdown_threshold=float(config.MAX_VALIDATED_DRAWDOWN),
    )
    regime = _regime_report(trade_rows)
    edge = _edge_report(trade_rows, regime)
    allocation = _allocation_report(trade_rows, enriched)
    suggestions = _optimization_suggestions(trade_rows, enriched, risk_reward, drawdown, regime)
    recommendation = _promotion_recommendation(gate, monte_carlo, len(trade_rows))
    run_id = _run_id(strategy_name)

    return _json_safe(
        {
            "run_id": run_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "strategy_name": strategy_name,
            "profile": profile,
            "start_date": start_date,
            "end_date": end_date,
            "symbols": symbols,
            "market_filters": market_filters,
            "starting_equity": starting_equity,
            "status": gate["status"],
            "validation_gate": gate,
            "backtest": enriched,
            "risk_reward": risk_reward,
            "drawdown": drawdown,
            "monte_carlo": monte_carlo,
            "market_regime": regime,
            "edge": edge,
            "capital_allocation": allocation,
            "optimization_suggestions": suggestions,
            "promotion_recommendation": recommendation,
            "trade_rows": trade_rows,
            "equity_curve": drawdown.get("series", []),
        }
    )


def save_research_lab_report(report: dict, output_dir: str = "research_results/research_lab") -> dict:
    os.makedirs(output_dir, exist_ok=True)
    run_id = report["run_id"]
    json_path = os.path.join(output_dir, f"{run_id}.json")
    markdown_path = os.path.join(output_dir, f"{run_id}.md")
    summary_path = os.path.join(output_dir, "research_lab_summary.csv")

    with open(json_path, "w", encoding="utf-8") as file:
        json.dump(report, file, indent=2)
    with open(markdown_path, "w", encoding="utf-8") as file:
        file.write(render_markdown_report(report))
    _append_summary(summary_path, report, json_path, markdown_path)
    return {"json_path": json_path, "markdown_path": markdown_path, "summary_path": summary_path}


def render_markdown_report(report: dict) -> str:
    backtest = report["backtest"]
    gate = report["validation_gate"]
    mc = report["monte_carlo"]
    rr = report["risk_reward"]
    drawdown = report["drawdown"]
    lines = [
        f"# Research Lab Report: {report['strategy_name']}",
        "",
        f"- Run ID: {report['run_id']}",
        f"- Profile: {report['profile']}",
        f"- Window: {report['start_date']} to {report['end_date']}",
        f"- Symbols: {', '.join(report['symbols'])}",
        f"- Market filters: {', '.join(report['market_filters']) or 'none'}",
        f"- Status: {report['status']}",
        f"- Recommendation: {report['promotion_recommendation']['recommendation']}",
        "",
        "## Backtest",
        "",
        f"- Starting equity: {_money(backtest.get('starting_equity'))}",
        f"- Ending equity: {_money(backtest.get('ending_equity'))}",
        f"- Total return: {_pct(backtest.get('total_return'))}",
        f"- CAGR: {_pct(backtest.get('cagr')) if backtest.get('cagr') is not None else 'not available'}",
        f"- Closed trades: {backtest.get('closed_trades')}",
        f"- Win rate: {_pct(backtest.get('win_rate'))}",
        f"- Profit factor: {_number(backtest.get('profit_factor'))}",
        f"- Expectancy: {_money(backtest.get('expectancy'))}",
        f"- Average R: {_number(rr.get('average_r_multiple'))}",
        f"- Best trade: {_money(backtest.get('best_trade'))}",
        f"- Worst trade: {_money(backtest.get('worst_trade'))}",
        f"- Average win: {_money(backtest.get('average_winner'))}",
        f"- Average loss: {_money(backtest.get('average_loser'))}",
        f"- Longest winning streak: {backtest.get('longest_winning_streak')}",
        f"- Longest losing streak: {backtest.get('longest_losing_streak')}",
        "",
        "## Validation Gate",
        "",
        f"- Passes: {gate.get('passes')}",
        *[f"- {reason}" for reason in gate.get("reasons", [])],
        "",
        "## Risk / Reward",
        "",
        rr.get("explanation", "not available"),
        "",
        f"- Average risk per trade: {_money(rr.get('average_risk_per_trade'))}",
        f"- Average reward per trade: {_money(rr.get('average_reward_per_trade'))}",
        f"- Reward-to-risk ratio: {_number(rr.get('reward_to_risk_ratio'))}",
        f"- Stop-loss hit rate: {_pct(rr.get('stop_loss_hit_rate'))}",
        f"- Take-profit hit rate: {_pct(rr.get('take_profit_hit_rate'))}",
        f"- Breakeven win rate: {_pct(rr.get('breakeven_win_rate'))}",
        "",
        "## Drawdown",
        "",
        f"- Max drawdown: {_pct(drawdown.get('max_drawdown'))}",
        f"- Average drawdown: {_pct(drawdown.get('average_drawdown'))}",
        f"- Max drawdown duration: {drawdown.get('max_drawdown_duration')} bars",
        f"- Average recovery time: {drawdown.get('average_recovery_time')}",
        f"- Worst recovery time: {drawdown.get('worst_recovery_time')}",
        f"- Current drawdown: {_pct(drawdown.get('current_drawdown'))}",
        "",
        "### Drawdown Reduction Suggestions",
        "",
        *[f"- {item}" for item in drawdown.get("suggestions", [])],
        "",
        "## Monte Carlo",
        "",
        f"- Runs: {mc.get('runs')}",
        f"- Median ending equity: {_money(mc.get('median_ending_equity'))}",
        f"- 5th percentile ending equity: {_money(mc.get('p5_ending_equity'))}",
        f"- 95th percentile ending equity: {_money(mc.get('p95_ending_equity'))}",
        f"- Probability of loss: {_pct(mc.get('probability_of_loss'))}",
        f"- Probability of breaching drawdown threshold: {_pct(mc.get('probability_of_breaching_max_drawdown'))}",
        f"- Worst simulated drawdown: {_pct(mc.get('worst_simulated_drawdown'))}",
        f"- Assessment: {mc.get('assessment')}",
        "",
        "## Market Regime",
        "",
        _markdown_table(report["market_regime"].get("performance_by_regime", [])),
        "",
        "## Edge",
        "",
        f"- Strength: {report['edge'].get('edge_strength')}",
        f"- Best symbols: {', '.join(report['edge'].get('best_symbols', [])) or 'not available'}",
        f"- Worst symbols: {', '.join(report['edge'].get('worst_symbols', [])) or 'not available'}",
        f"- Best time windows: {', '.join(report['edge'].get('best_time_windows', [])) or 'not available'}",
        f"- Worst time windows: {', '.join(report['edge'].get('worst_time_windows', [])) or 'not available'}",
        "",
        "## Optimization Suggestions",
        "",
        *[f"- {item['change']}: {item['why']} Expected improvement: {item['expected_improvement']} Risk: {item['risk']} Validation: {item['validation_step']}" for item in report.get("optimization_suggestions", [])],
        "",
        "## Capital Allocation",
        "",
        *[f"- {key.replace('_', ' ').title()}: {value}" for key, value in report["capital_allocation"].items()],
        "",
        "Live trading remains disabled. This report is research evidence only.",
        "",
    ]
    return "\n".join(lines)


def _enrich_backtest_report(report: dict, trade_rows: list[dict], equity_curve: list[dict], starting_equity: float, start_date: str, end_date: str) -> dict:
    data = pd.DataFrame(trade_rows)
    ending_equity = _ending_equity(equity_curve, starting_equity)
    enriched = dict(report)
    enriched["starting_equity"] = float(starting_equity)
    enriched["ending_equity"] = ending_equity
    enriched["total_return"] = (ending_equity - float(starting_equity)) / float(starting_equity) if starting_equity else None
    enriched["cagr"] = _cagr(starting_equity, ending_equity, start_date, end_date)

    if data.empty:
        enriched.update(
            {
                "best_trade": None,
                "worst_trade": None,
                "average_r": None,
                "longest_winning_streak": 0,
                "longest_losing_streak": 0,
                "trades_by_symbol": [],
                "trades_by_weekday": [],
                "trades_by_time_of_day": [],
                "trades_by_exit_reason": [],
            }
        )
        return enriched

    data["pnl_dollars"] = pd.to_numeric(data["pnl_dollars"], errors="coerce").fillna(0.0)
    data["entry_timestamp"] = pd.to_datetime(data["entry_timestamp"], errors="coerce")
    enriched["best_trade"] = float(data["pnl_dollars"].max())
    enriched["worst_trade"] = float(data["pnl_dollars"].min())
    enriched["longest_winning_streak"] = _streak(data["pnl_dollars"], True)
    enriched["longest_losing_streak"] = _streak(data["pnl_dollars"], False)
    enriched["trades_by_symbol"] = _group_stats(data, "ticker")
    enriched["trades_by_weekday"] = _group_stats(data.assign(weekday=data["entry_timestamp"].dt.day_name()), "weekday")
    enriched["trades_by_time_of_day"] = _group_stats(data.assign(entry_hour=data["entry_timestamp"].dt.hour), "entry_hour")
    enriched["trades_by_exit_reason"] = _group_stats(data, "exit_reason")
    enriched["total_pnl"] = float(data["pnl_dollars"].sum())
    return enriched


def _normalize_trade_rows(trade_rows: list[dict]) -> list[dict]:
    optional_fields = {
        "setup_type": None,
        "rsi": None,
        "rvol": None,
        "exit_reason": None,
    }
    normalized = []
    for row in trade_rows:
        item = {**optional_fields, **dict(row)}
        for field in ("entry_timestamp", "exit_timestamp"):
            if field in item:
                item[field] = pd.to_datetime(item[field], utc=True, errors="coerce")
        normalized.append(item)
    return normalized


def _group_stats(data: pd.DataFrame, column: str) -> list[dict]:
    if column not in data or data.empty:
        return []
    grouped = data.groupby(column, dropna=False)["pnl_dollars"].agg(["count", "sum", "mean"])
    wins = data.assign(is_win=data["pnl_dollars"] > 0).groupby(column, dropna=False)["is_win"].mean()
    rows = []
    for key, row in grouped.reset_index().iterrows():
        label = row[column]
        rows.append(
            {
                "name": str(label),
                "closed_trades": int(row["count"]),
                "total_pnl": float(row["sum"]),
                "expectancy": float(row["mean"]),
                "win_rate": float(wins.loc[label]) if label in wins.index else None,
            }
        )
    return sorted(rows, key=lambda item: item["total_pnl"], reverse=True)


def _regime_report(trade_rows: list[dict]) -> dict:
    data = pd.DataFrame(trade_rows)
    if data.empty:
        return {"performance_by_regime": [], "avoid": "not available: no closed trades"}
    regime_column = "spy_trend" if "spy_trend" in data else "market_regime"
    if regime_column not in data:
        return {"performance_by_regime": [], "avoid": "not available: no regime labels on trades"}
    stats = _group_stats(data.rename(columns={regime_column: "regime"}), "regime")
    avoid = [row["name"] for row in stats if row["expectancy"] < 0]
    return {
        "performance_by_regime": stats,
        "avoid": ", ".join(avoid) if avoid else "No historically negative regime bucket in this sample.",
    }


def _edge_report(trade_rows: list[dict], regime: dict) -> dict:
    data = pd.DataFrame(trade_rows)
    if data.empty:
        return {
            "best_symbols": [],
            "worst_symbols": [],
            "best_time_windows": [],
            "worst_time_windows": [],
            "best_regimes": [],
            "weaknesses": ["No closed trades yet."],
            "edge_strength": "unproven",
        }
    data["pnl_dollars"] = pd.to_numeric(data["pnl_dollars"], errors="coerce").fillna(0.0)
    data["entry_timestamp"] = pd.to_datetime(data["entry_timestamp"], errors="coerce")
    by_symbol = _group_stats(data, "ticker")
    by_hour = _group_stats(data.assign(entry_hour=data["entry_timestamp"].dt.hour), "entry_hour")
    best_regimes = [row["name"] for row in regime.get("performance_by_regime", [])[:3]]
    weaknesses = [f"{row['name']} has negative expectancy" for row in by_symbol if row["expectancy"] < 0]
    pf = _profit_factor(data["pnl_dollars"])
    expectancy = float(data["pnl_dollars"].mean())
    if len(data) < 30:
        strength = "unproven"
    elif pf >= 1.25 and expectancy > 0:
        strength = "moderate"
    elif pf > 1.0 and expectancy > 0:
        strength = "weak"
    else:
        strength = "not proven"
    return {
        "best_symbols": [row["name"] for row in by_symbol[:3]],
        "worst_symbols": [row["name"] for row in sorted(by_symbol, key=lambda item: item["total_pnl"])[:3]],
        "best_time_windows": [str(row["name"]) for row in by_hour[:3]],
        "worst_time_windows": [str(row["name"]) for row in sorted(by_hour, key=lambda item: item["total_pnl"])[:3]],
        "best_regimes": best_regimes,
        "weaknesses": weaknesses or ["No obvious single destructive bucket in this sample."],
        "edge_strength": strength,
    }


def _allocation_report(trade_rows: list[dict], report: dict) -> dict:
    return {
        "recommended_max_capital_per_trade": f"{float(config.MAX_CAPITAL_PER_TRADE) * 100:.1f}% baseline; do not increase until paper results pass gate",
        "recommended_max_daily_loss": f"Current baseline: {float(config.MAX_DAILY_LOSS_PERCENT) * 100:.1f}% or ${float(config.MAX_DAILY_LOSS_DOLLARS):.0f}",
        "recommended_max_concurrent_positions": min(int(config.MAX_POSITIONS), int(getattr(config, "ORVWAP_MAX_POSITIONS", config.MAX_POSITIONS))),
        "recommended_symbol_level_exposure_limits": "Keep single-symbol exposure at or below current per-trade cap until symbol scorecards are stable.",
        "risk_setting_assessment": _risk_setting_assessment(report),
        "symbols_to_review_or_exclude": ", ".join(_negative_symbols(trade_rows)) or "none from this sample",
    }


def _optimization_suggestions(trade_rows: list[dict], report: dict, risk_reward: dict, drawdown: dict, regime: dict) -> list[dict]:
    suggestions = []
    bad_symbols = _negative_symbols(trade_rows)
    if bad_symbols:
        suggestions.append(_suggestion(
            f"Test excluding {bad_symbols[0]}",
            "This symbol has negative total PnL in the sample.",
            "Improve expectancy and drawdown stability.",
            "May remove future winners if the sample is too small.",
            "Run walk-forward validation with and without the exclusion.",
        ))
    if report.get("worst_time_of_day") is not None:
        suggestions.append(_suggestion(
            f"Test blocking entries near hour {report['worst_time_of_day']}",
            "The existing analytics identified this as the weakest time-of-day bucket.",
            "Reduce clustered intraday losses.",
            "Could reduce trade count below validation thresholds.",
            "Re-run Research Lab with the blocked hour and compare out-of-sample folds.",
        ))
    if risk_reward.get("current_win_rate_clears_breakeven") is False:
        suggestions.append(_suggestion(
            "Review Target R and stop selection",
            "Observed win rate does not clear estimated breakeven for the payoff profile.",
            "Improve payoff balance or breakeven requirements.",
            "Tighter targets may cap winners; tighter stops may increase stop-outs.",
            "Validate one parameter change at a time with walk-forward testing.",
        ))
    if regime.get("avoid") and not str(regime["avoid"]).startswith("No historically"):
        suggestions.append(_suggestion(
            "Tighten market filter strictness",
            f"Negative regime buckets were observed: {regime['avoid']}.",
            "Avoid trades during historically weak market conditions.",
            "May skip profitable reversals or reduce opportunity.",
            "Compare fold-level expectancy before and after the stricter filter.",
        ))
    while len(suggestions) < 3:
        suggestions.append(_suggestion(
            "Do not change production parameters yet",
            "The report does not show enough repeated evidence for another safe recommendation.",
            "Avoid overfitting.",
            "Progress may be slower because fewer ideas are tested.",
            "Collect more trades or run a longer out-of-sample window.",
        ))
    return suggestions[:5]


def _promotion_recommendation(gate: dict, monte_carlo: dict, trade_count: int) -> dict:
    if trade_count < 30:
        return {
            "recommendation": "Keep RESEARCH_ONLY",
            "reason": "Too few closed trades for promotion.",
        }
    if not gate.get("passes"):
        return {
            "recommendation": "Keep RESEARCH_ONLY",
            "reason": "Backtest validation gate failed.",
        }
    if monte_carlo.get("probability_of_loss") is not None and monte_carlo["probability_of_loss"] > 0.35:
        return {
            "recommendation": "Keep RESEARCH_ONLY",
            "reason": "Monte Carlo probability of loss is too high.",
        }
    return {
        "recommendation": "PAPER_CANDIDATE",
        "reason": "Backtest gate passed; paper trading validation is still required before live trading.",
    }


def _append_summary(summary_path: str, report: dict, json_path: str, markdown_path: str) -> None:
    row = {
        "run_id": report["run_id"],
        "created_at": report["created_at"],
        "strategy": report["strategy_name"],
        "profile": report["profile"],
        "status": report["status"],
        "passes_gate": report["validation_gate"].get("passes"),
        "start_date": report["start_date"],
        "end_date": report["end_date"],
        "symbols": ",".join(report["symbols"]),
        "closed_trades": report["backtest"].get("closed_trades"),
        "total_return": report["backtest"].get("total_return"),
        "profit_factor": report["backtest"].get("profit_factor"),
        "expectancy": report["backtest"].get("expectancy"),
        "win_rate": report["backtest"].get("win_rate"),
        "max_drawdown": report["backtest"].get("max_drawdown"),
        "monte_carlo_probability_of_loss": report["monte_carlo"].get("probability_of_loss"),
        "recommendation": report["promotion_recommendation"].get("recommendation"),
        "json_path": json_path,
        "markdown_path": markdown_path,
    }
    write_header = not os.path.exists(summary_path)
    with open(summary_path, "a", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=SUMMARY_FIELDS)
        if write_header:
            writer.writeheader()
        writer.writerow(row)


def _ending_equity(equity_curve: list[dict], starting_equity: float) -> float:
    if not equity_curve:
        return float(starting_equity)
    return float(equity_curve[-1].get("equity", starting_equity))


def _cagr(starting_equity: float, ending_equity: float, start_date: str, end_date: str) -> float | None:
    days = (pd.Timestamp(end_date) - pd.Timestamp(start_date)).days
    if days < 180 or starting_equity <= 0 or ending_equity <= 0:
        return None
    years = days / 365.25
    return float((ending_equity / starting_equity) ** (1 / years) - 1)


def _streak(series: pd.Series, winning: bool) -> int:
    max_streak = 0
    current = 0
    for value in series:
        condition = value > 0 if winning else value <= 0
        if condition:
            current += 1
            max_streak = max(max_streak, current)
        else:
            current = 0
    return max_streak


def _negative_symbols(trade_rows: list[dict]) -> list[str]:
    data = pd.DataFrame(trade_rows)
    if data.empty or "ticker" not in data:
        return []
    data["pnl_dollars"] = pd.to_numeric(data["pnl_dollars"], errors="coerce").fillna(0.0)
    grouped = data.groupby("ticker")["pnl_dollars"].sum().sort_values()
    return [str(symbol) for symbol, pnl in grouped.items() if pnl < 0]


def _profit_factor(series: pd.Series) -> float:
    wins = series[series > 0].sum()
    losses = abs(series[series <= 0].sum())
    return float(wins / losses) if losses > 0 else math.inf


def _risk_setting_assessment(report: dict) -> str:
    if report.get("max_drawdown", 0.0) > float(config.MAX_VALIDATED_DRAWDOWN):
        return "Current settings are too aggressive for the observed drawdown."
    if report.get("closed_trades", 0) < 30:
        return "Not enough trades to judge risk settings."
    return "Current settings are reasonable for research; keep them unchanged until paper validation."


def _suggestion(change: str, why: str, expected: str, risk: str, validation: str) -> dict:
    return {
        "change": change,
        "why": why,
        "expected_improvement": expected,
        "risk": risk,
        "validation_step": validation,
    }


def _run_id(strategy_name: str) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    slug = "".join(char if char.isalnum() else "_" for char in strategy_name.lower()).strip("_")
    return f"{timestamp}_research_lab_{slug}_{uuid4().hex[:8]}"


def _markdown_table(rows: list[dict]) -> str:
    if not rows:
        return "not available"
    columns = list(rows[0].keys())
    lines = ["| " + " | ".join(columns) + " |", "| " + " | ".join(["---"] * len(columns)) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(str(row.get(column, "")) for column in columns) + " |")
    return "\n".join(lines)


def _money(value) -> str:
    if value is None:
        return "not available"
    return f"${float(value):,.2f}"


def _pct(value) -> str:
    if value is None:
        return "not available"
    return f"{float(value) * 100:.2f}%"


def _number(value) -> str:
    if value is None:
        return "not available"
    if value == "Infinity" or value == math.inf:
        return "Infinity"
    return f"{float(value):.2f}"


def _json_safe(value):
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    if hasattr(value, "item"):
        try:
            return _json_safe(value.item())
        except (TypeError, ValueError):
            pass
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, float):
        if math.isnan(value):
            return None
        if math.isinf(value):
            return "Infinity" if value > 0 else "-Infinity"
    return value
