"""Report builder for ORB-PBC v1.0 research runs.

Produces a JSON report, a Markdown report, and an appended row in a shared
CSV summary, following the same on-disk conventions as
``analytics/research_lab.py`` (``research_results/<run>/{run_id}.json`` /
``.md`` + a summary CSV), but with the additional sections the ORB-PBC spec
explicitly requires (edge hypothesis, implementation fidelity checklist,
data-availability caveats, cost/slippage assumptions, walk-forward, Monte
Carlo, slippage stress, and an explicit pass/fail table).
"""

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
from strategies.orb_pullback_continuation import EDGE_HYPOTHESIS, FIDELITY_CHECKLIST
from validation.orb_pbc_gate import evaluate_orb_pbc_gate
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
    "trades_per_year",
    "profit_factor_after_costs",
    "profit_factor_before_costs",
    "avg_r_multiple",
    "expectancy",
    "win_rate",
    "max_drawdown",
    "monte_carlo_probability_of_loss",
    "slippage_stress_pf",
    "walk_forward_efficiency",
    "recommendation",
    "json_path",
    "markdown_path",
]


def build_orb_pbc_report(
    *,
    profile: str,
    start_date: str,
    end_date: str,
    symbols: list[str],
    market_filters: list[str],
    starting_equity: float,
    result_after_costs,
    result_before_costs=None,
    result_slippage_stress=None,
    walk_forward: dict | None = None,
    monte_carlo_runs: int = 1000,
) -> dict:
    trade_rows = result_after_costs.trade_rows
    equity_curve = result_after_costs.equity_curve

    report_after_costs = calculate_report(trade_rows, equity_curve)
    report_after_costs = _enrich(report_after_costs, trade_rows, equity_curve, starting_equity, start_date, end_date)

    report_before_costs = None
    if result_before_costs is not None:
        report_before_costs = calculate_report(result_before_costs.trade_rows, result_before_costs.equity_curve)

    slippage_stress_report = None
    if result_slippage_stress is not None:
        slippage_stress_report = calculate_report(
            result_slippage_stress.trade_rows, result_slippage_stress.equity_curve
        )

    generic_gate = evaluate_validation_gate(report_after_costs, stage="backtest")
    risk_reward = analyze_risk_reward(trade_rows)
    drawdown = analyze_drawdowns(equity_curve, trade_rows)
    monte_carlo = run_monte_carlo(
        trade_rows,
        starting_equity,
        runs=monte_carlo_runs,
        max_drawdown_threshold=float(config.ORB_PBC_MAX_DRAWDOWN_PCT),
    )

    orb_gate = evaluate_orb_pbc_gate(
        report_after_costs=report_after_costs,
        trade_rows=trade_rows,
        report_before_costs=report_before_costs,
        monte_carlo=monte_carlo,
        walk_forward=walk_forward,
        slippage_stress_report=slippage_stress_report,
        drawdown=drawdown,
    )

    data_caveats = list(result_after_costs.data_notes)
    data_caveats.append(
        "Historical 1-minute OHLCV in this repo spans roughly 2025-09 through "
        "2026-06 (~9 months), not the 2-3 years the spec asks the backtest to "
        "target. Trade-count and per-year gates are evaluated honestly "
        "against this shorter window rather than extrapolated or padded."
    )
    data_caveats.append(
        "No bid/ask spread data exists in the historical CSVs used here. The "
        "spread_pct <= 0.0005 filter is therefore marked UNAVAILABLE and is "
        "not enforced in this backtest (spread_available=False everywhere) "
        "rather than being approximated with a fabricated spread."
    )
    data_caveats.append(
        "No FOMC/economic calendar exists in this repo. The FOMC-specific "
        "block is not implemented; the strategy's own 11:15 ET entry cutoff "
        "makes a 13:30-14:00 FOMC block moot for v1.0. Documented as a TODO."
    )

    recommendation = _promotion_recommendation(orb_gate, generic_gate, len(trade_rows))
    run_id = _run_id()

    return _json_safe(
        {
            "run_id": run_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "strategy_name": config.ORB_PBC_STRATEGY_NAME,
            "strategy_version": "1.0",
            "profile": profile,
            "start_date": start_date,
            "end_date": end_date,
            "symbols": symbols,
            "market_filters": market_filters,
            "starting_equity": starting_equity,
            "status": orb_gate["status"],
            "recommendation": recommendation,
            "edge_hypothesis": EDGE_HYPOTHESIS,
            "implementation_fidelity_checklist": {
                key: {"implemented": value[0], "detail": value[1]} for key, value in FIDELITY_CHECKLIST.items()
            },
            "data_availability_caveats": data_caveats,
            "backtest_after_costs": report_after_costs,
            "backtest_before_costs": report_before_costs,
            "slippage_stress_2x": slippage_stress_report,
            "cost_model": {
                "commission_per_share": config.ORB_PBC_COMMISSION_PER_SHARE,
                "default_slippage_per_share": config.ORB_PBC_DEFAULT_SLIPPAGE_PER_SHARE,
                "tsla_slippage_per_share": config.ORB_PBC_TSLA_SLIPPAGE_PER_SHARE,
                "slippage_stress_multiplier": config.ORB_PBC_SLIPPAGE_STRESS_MULTIPLIER,
            },
            "risk_reward": risk_reward,
            "drawdown": drawdown,
            "monte_carlo": monte_carlo,
            "walk_forward": walk_forward,
            "validation_gate_generic": generic_gate,
            "validation_gate_orb_pbc": orb_gate,
            "diagnostics": result_after_costs.diagnostics,
            "trade_rows": trade_rows,
            "equity_curve": drawdown.get("series", []),
        }
    )


def save_orb_pbc_report(report: dict, output_dir: str = "research_results/orb_pbc_v1") -> dict:
    os.makedirs(output_dir, exist_ok=True)
    run_id = report["run_id"]
    json_path = os.path.join(output_dir, f"{run_id}.json")
    markdown_path = os.path.join(output_dir, f"{run_id}.md")
    summary_path = os.path.join(output_dir, "orb_pbc_summary.csv")

    with open(json_path, "w", encoding="utf-8") as file:
        json.dump(report, file, indent=2)
    with open(markdown_path, "w", encoding="utf-8") as file:
        file.write(render_orb_pbc_markdown(report))
    _append_summary(summary_path, report, json_path, markdown_path)
    return {"json_path": json_path, "markdown_path": markdown_path, "summary_path": summary_path}


def render_orb_pbc_markdown(report: dict) -> str:
    backtest = report["backtest_after_costs"]
    before = report.get("backtest_before_costs") or {}
    stress = report.get("slippage_stress_2x") or {}
    gate = report["validation_gate_orb_pbc"]
    mc = report["monte_carlo"] or {}
    rr = report["risk_reward"] or {}
    drawdown = report["drawdown"] or {}
    wf = report.get("walk_forward")

    lines = [
        f"# ORB-PBC v1.0 Research Report -- {report['strategy_name']}",
        "",
        f"- Run ID: {report['run_id']}",
        f"- Profile: {report['profile']}",
        f"- Window: {report['start_date']} to {report['end_date']}",
        f"- Symbols: {', '.join(report['symbols'])}",
        f"- Market filters: {', '.join(report['market_filters'])}",
        f"- **Status: {report['status']}**",
        f"- **Recommendation: {report['recommendation']['recommendation']}**",
        f"- Reason: {report['recommendation']['reason']}",
        "",
        "## 1. Strategy Summary",
        "",
        "ORB-PBC v1.0 (Opening Range Breakout Pullback Continuation) is a "
        "long-only, research-only intraday strategy. It never buys the "
        "breakout candle: it confirms a 5-minute close above the 15-minute "
        "opening range high, waits for a held pullback, and enters only on "
        "a break of the pullback bar's high.",
        "",
        "## 2. Edge Hypothesis",
        "",
        report["edge_hypothesis"],
        "",
        "## 3. Implementation Fidelity Checklist",
        "",
        *[
            f"- [{'x' if item['implemented'] is True else ('~' if item['implemented'] == 'conditional' else ' ')}] "
            f"**{name}**: {item['detail']}"
            for name, item in report["implementation_fidelity_checklist"].items()
        ],
        "",
        "## 4. Data Availability and Caveats",
        "",
        *[f"- {item}" for item in report["data_availability_caveats"]],
        "",
        "## 5. Backtest Results (after costs)",
        "",
        f"- Starting equity: {_money(backtest.get('starting_equity'))}",
        f"- Ending equity: {_money(backtest.get('ending_equity'))}",
        f"- Total return: {_pct(backtest.get('total_return'))}",
        f"- CAGR: {_pct(backtest.get('cagr')) if backtest.get('cagr') is not None else 'not available (insufficient period)'}",
        f"- Closed trades: {backtest.get('closed_trades')}",
        f"- Trades per year (estimated): {_number(gate.get('trades_per_year'))}",
        f"- Win rate: {_pct(backtest.get('win_rate'))}",
        f"- Profit factor (after costs): {_number(backtest.get('profit_factor'))}",
        f"- Profit factor (before costs): {_number(gate.get('profit_factor_before_costs'))}",
        f"- Expectancy: {_money(backtest.get('expectancy'))}",
        f"- Average R multiple: {_number(gate.get('avg_r_multiple'))}",
        f"- Best trade: {_money(backtest.get('best_trade'))}",
        f"- Worst trade: {_money(backtest.get('worst_trade'))}",
        f"- Average win: {_money(backtest.get('average_winner'))}",
        f"- Average loss: {_money(backtest.get('average_loser'))}",
        f"- Longest winning streak: {backtest.get('longest_winning_streak')}",
        f"- Longest losing streak: {backtest.get('longest_losing_streak')}",
        "",
        "## 6. Costs and Slippage Assumptions",
        "",
        f"- Commission: ${report['cost_model']['commission_per_share']:.3f}/share",
        f"- Default slippage: ${report['cost_model']['default_slippage_per_share']:.3f}/share",
        f"- TSLA slippage: ${report['cost_model']['tsla_slippage_per_share']:.3f}/share",
        f"- Slippage stress multiplier: {report['cost_model']['slippage_stress_multiplier']}x",
        f"- 2x slippage stress profit factor: {_number(stress.get('profit_factor'))}",
        f"- 2x slippage stress closed trades: {stress.get('closed_trades', 'not available')}",
        "",
        "## 7. Risk / Reward Metrics",
        "",
        rr.get("explanation", "not available"),
        f"- Average risk per trade: {_money(rr.get('average_risk_per_trade'))}",
        f"- Average reward per trade: {_money(rr.get('average_reward_per_trade'))}",
        f"- Stop-loss hit rate: {_pct(rr.get('stop_loss_hit_rate'))}",
        "",
        "## 8. Drawdown Analysis",
        "",
        f"- Max drawdown: {_pct(drawdown.get('max_drawdown'))}",
        f"- Max drawdown duration: {drawdown.get('max_drawdown_duration')} bars "
        f"(~{_number(gate.get('longest_drawdown_months_estimate'))} months)",
        f"- Current drawdown: {_pct(drawdown.get('current_drawdown'))}",
        "",
        "## 9. Symbol Breakdown",
        "",
        _symbol_table(gate.get("symbol_concentration", {})),
        f"- Best-symbol-removed profit factor: {_number(gate.get('best_symbol_removed_pf'))}",
        "",
        "## 10. Monthly Breakdown",
        "",
        _monthly_table(gate.get("monthly_profitability", {})),
        f"- Monthly profitable %: {_pct(gate.get('monthly_profitability', {}).get('monthly_profitable_pct'))}",
        "",
        "## 11. Regime Breakdown",
        "",
        "not available: this backtest does not yet tag trades with a "
        "trending-up/choppy/trending-down daily regime label.",
        "",
        "## 12. Exit Reason Breakdown",
        "",
        _exit_reason_table(backtest.get("trades_by_exit_reason", [])),
        "",
        "## 13. Walk-Forward Results",
        "",
        *(_walk_forward_lines(wf) if wf else ["not run for this profile."]),
        "",
        "## 14. Monte Carlo Results",
        "",
        f"- Runs: {mc.get('runs')}",
        f"- Median ending equity: {_money(mc.get('median_ending_equity'))}",
        f"- 5th percentile ending equity: {_money(mc.get('p5_ending_equity'))}",
        f"- 95th percentile ending equity: {_money(mc.get('p95_ending_equity'))}",
        f"- Worst simulated drawdown: {_pct(mc.get('worst_simulated_drawdown'))}",
        f"- P(negative total return): {_pct(mc.get('probability_of_loss'))}",
        f"- P(max drawdown > {config.ORB_PBC_MAX_DRAWDOWN_PCT * 100:.0f}%): "
        f"{_pct(mc.get('probability_of_breaching_max_drawdown'))}",
        f"- Assessment: {mc.get('assessment')}",
        "",
        "## 15. 2x Slippage Stress Test",
        "",
        f"- Profit factor under 2x slippage: {_number(stress.get('profit_factor'))} "
        f"(baseline after-costs PF: {_number(backtest.get('profit_factor'))})",
        f"- Closed trades under 2x slippage: {stress.get('closed_trades', 'not available')}",
        "",
        "## 16. Pass / Fail Validation Table",
        "",
        _criteria_table(gate.get("criteria", [])),
        "",
        "## 17. Failure Conditions Triggered",
        "",
        *(
            [f"- {reason}" for reason in gate.get("reject_reasons_triggered", [])]
            or ["- None of the explicit REJECT conditions were triggered."]
        ),
        "",
        "## 18. Recommendation",
        "",
        f"**{report['recommendation']['recommendation']}** -- {report['recommendation']['reason']}",
        "",
        "Live trading remains disabled. `config.TRADING_MODE` and all "
        "live-trading flags are untouched by this strategy and this report.",
        "",
        "## 19. Next Actions",
        "",
        *[f"- {item}" for item in _next_actions(gate, backtest)],
        "",
    ]
    return "\n".join(lines)


def _enrich(report, trade_rows, equity_curve, starting_equity, start_date, end_date) -> dict:
    data = pd.DataFrame(trade_rows)
    ending_equity = float(equity_curve[-1]["equity"]) if equity_curve else float(starting_equity)
    enriched = dict(report)
    enriched["starting_equity"] = float(starting_equity)
    enriched["ending_equity"] = ending_equity
    enriched["total_return"] = (
        (ending_equity - float(starting_equity)) / float(starting_equity) if starting_equity else None
    )
    days = (pd.Timestamp(end_date) - pd.Timestamp(start_date)).days
    enriched["cagr"] = None
    if days >= 180 and starting_equity > 0 and ending_equity > 0:
        years = days / 365.25
        enriched["cagr"] = float((ending_equity / starting_equity) ** (1 / years) - 1)

    if data.empty:
        enriched["best_trade"] = None
        enriched["worst_trade"] = None
        enriched["longest_winning_streak"] = 0
        enriched["longest_losing_streak"] = 0
        enriched["trades_by_exit_reason"] = []
        return enriched

    data["pnl_dollars"] = pd.to_numeric(data["pnl_dollars"], errors="coerce").fillna(0.0)
    enriched["best_trade"] = float(data["pnl_dollars"].max())
    enriched["worst_trade"] = float(data["pnl_dollars"].min())
    enriched["longest_winning_streak"] = _streak(data["pnl_dollars"], True)
    enriched["longest_losing_streak"] = _streak(data["pnl_dollars"], False)
    enriched["trades_by_exit_reason"] = _group_stats(data, "exit_reason")
    return enriched


def _group_stats(data: pd.DataFrame, column: str) -> list[dict]:
    if column not in data or data.empty:
        return []
    grouped = data.groupby(column, dropna=False)["pnl_dollars"].agg(["count", "sum", "mean"])
    rows = []
    for label, row in grouped.iterrows():
        rows.append(
            {
                "name": str(label),
                "closed_trades": int(row["count"]),
                "total_pnl": float(row["sum"]),
                "expectancy": float(row["mean"]),
            }
        )
    return sorted(rows, key=lambda item: item["total_pnl"], reverse=True)


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


def _promotion_recommendation(orb_gate: dict, generic_gate: dict, trade_count: int) -> dict:
    if trade_count == 0:
        return {
            "recommendation": "RESEARCH_ONLY",
            "reason": "Zero closed trades in this window; the filter stack is working exactly "
            "as specified (no shortcuts taken to force trades), but there is no evidence yet "
            "either way.",
        }
    if orb_gate["passes"]:
        return {
            "recommendation": "PAPER_CANDIDATE",
            "reason": "All available ORB-PBC validation criteria passed. Live trading is still "
            "not recommended and remains disabled; paper trading with broker reconciliation is "
            "the required next step.",
        }
    if orb_gate.get("reject_reasons_triggered"):
        return {
            "recommendation": "RESEARCH_ONLY",
            "reason": "One or more explicit REJECT conditions were triggered: "
            + "; ".join(orb_gate["reject_reasons_triggered"]),
        }
    return {
        "recommendation": "RESEARCH_ONLY",
        "reason": "Backtest gate did not clear the ORB-PBC v1.0 validation checklist "
        f"(closed_trades={trade_count}). See the pass/fail table for specifics.",
    }


def _next_actions(gate: dict, backtest: dict) -> list[str]:
    actions = []
    closed_trades = backtest.get("closed_trades", 0) or 0
    if closed_trades < config.ORB_PBC_MIN_TRADES:
        actions.append(
            f"Collect more historical 1-minute data (true 2-3 years) before drawing conclusions -- "
            f"only {closed_trades} trades were produced in the available ~9-month window, well "
            f"below the {config.ORB_PBC_MIN_TRADES}-trade gate. Do not loosen filters to compensate."
        )
    actions.append("Run the optional all-7-symbol comparison profile and compare filter-driven inclusion/exclusion.")
    actions.append("Run walk-forward validation once enough history exists for a full 6-month train / 3-month test fold.")
    actions.append("Re-run Monte Carlo with 10,000 runs once trade count is large enough for the result to be stable.")
    if not gate.get("passes"):
        actions.append("Keep RESEARCH_ONLY. Do not enable paper or live trading for this strategy.")
    return actions


def _symbol_table(concentration: dict) -> str:
    by_symbol = concentration.get("by_symbol_pnl") or {}
    if not by_symbol:
        return "not available: no closed trades."
    lines = ["| Symbol | Net PnL |", "| --- | --- |"]
    for symbol, pnl in sorted(by_symbol.items(), key=lambda item: item[1], reverse=True):
        lines.append(f"| {symbol} | {_money(pnl)} |")
    return "\n".join(lines)


def _monthly_table(monthly: dict) -> str:
    months = monthly.get("months") or []
    if not months:
        return f"not available: {monthly.get('reason', 'no trades')}."
    lines = ["| Month | PnL |", "| --- | --- |"]
    for entry in months:
        lines.append(f"| {entry['month']} | {_money(entry['pnl'])} |")
    return "\n".join(lines)


def _exit_reason_table(rows: list[dict]) -> str:
    if not rows:
        return "not available: no closed trades."
    lines = ["| Exit Reason | Trades | Total PnL | Expectancy |", "| --- | --- | --- | --- |"]
    for row in rows:
        lines.append(
            f"| {row['name']} | {row['closed_trades']} | {_money(row['total_pnl'])} | {_money(row['expectancy'])} |"
        )
    return "\n".join(lines)


def _criteria_table(criteria: list[dict]) -> str:
    if not criteria:
        return "not available."
    lines = ["| Criterion | Result | Detail |", "| --- | --- | --- |"]
    for item in criteria:
        if item["passed"] is None:
            result = "NOT AVAILABLE"
        elif item["passed"]:
            result = "PASS"
        else:
            result = "FAIL"
        lines.append(f"| {item['name']} | {result} | {item['detail']} |")
    return "\n".join(lines)


def _walk_forward_lines(wf: dict) -> list[str]:
    return [
        f"- Folds run: {wf.get('folds_run')}",
        f"- Walk-forward efficiency (OOS avg R / IS avg R): {_number(wf.get('walk_forward_efficiency'))}",
        f"- OOS profitable window %: {_pct(wf.get('oos_profitable_window_pct'))}",
        f"- Notes: {wf.get('notes', 'none')}",
    ]


def _append_summary(summary_path: str, report: dict, json_path: str, markdown_path: str) -> None:
    gate = report["validation_gate_orb_pbc"]
    backtest = report["backtest_after_costs"]
    row = {
        "run_id": report["run_id"],
        "created_at": report["created_at"],
        "strategy": report["strategy_name"],
        "profile": report["profile"],
        "status": report["status"],
        "passes_gate": gate.get("passes"),
        "start_date": report["start_date"],
        "end_date": report["end_date"],
        "symbols": ",".join(report["symbols"]),
        "closed_trades": backtest.get("closed_trades"),
        "trades_per_year": gate.get("trades_per_year"),
        "profit_factor_after_costs": backtest.get("profit_factor"),
        "profit_factor_before_costs": gate.get("profit_factor_before_costs"),
        "avg_r_multiple": gate.get("avg_r_multiple"),
        "expectancy": backtest.get("expectancy"),
        "win_rate": backtest.get("win_rate"),
        "max_drawdown": backtest.get("max_drawdown"),
        "monte_carlo_probability_of_loss": report["monte_carlo"].get("probability_of_loss") if report.get("monte_carlo") else None,
        "slippage_stress_pf": (report.get("slippage_stress_2x") or {}).get("profit_factor"),
        "walk_forward_efficiency": (report.get("walk_forward") or {}).get("walk_forward_efficiency"),
        "recommendation": report["recommendation"]["recommendation"],
        "json_path": json_path,
        "markdown_path": markdown_path,
    }
    write_header = not os.path.exists(summary_path)
    with open(summary_path, "a", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=SUMMARY_FIELDS)
        if write_header:
            writer.writeheader()
        writer.writerow(row)


def _run_id() -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return f"{timestamp}_orb_pbc_v1_{uuid4().hex[:8]}"


def _money(value) -> str:
    if value is None:
        return "not available"
    try:
        return f"${float(value):,.2f}"
    except (TypeError, ValueError):
        return "not available"


def _pct(value) -> str:
    if value is None:
        return "not available"
    try:
        return f"{float(value) * 100:.2f}%"
    except (TypeError, ValueError):
        return "not available"


def _number(value) -> str:
    if value is None:
        return "not available"
    if value == math.inf:
        return "Infinity"
    try:
        return f"{float(value):.3f}"
    except (TypeError, ValueError):
        return "not available"


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
