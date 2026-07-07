"""Streamlit dashboard — PAPER-only trading platform with ML Brain visibility."""

from __future__ import annotations

import json
import subprocess

import pandas as pd
import streamlit as st

import config
from dashboard.commands import PROJECT_ROOT, command_env, python_command
from dashboard.data_loader import (
    bot_status,
    candidate_trades_table,
    load_labeled_candidates,
    load_ml_metadata,
    load_ml_predictions,
    load_research_report,
    load_signal_log,
    load_trade_log,
    ml_filter_summary,
)
from dashboard.readme_page import render_readme_page
from dashboard.ui_components import (
    fmt,
    hero,
    info_box,
    inject_styles,
    metric_row,
    status_pill,
    warn_box,
)


def _py_command(script: str, *args: str) -> list[str]:
    return python_command(script, *args)


def _run_command(label: str, command: list[str], *, refresh_on_success: bool = False) -> bool:
    with st.status(label, expanded=True) as status:
        try:
            result = subprocess.run(
                command, capture_output=True, text=True, check=False,
                timeout=600, cwd=PROJECT_ROOT, env=command_env(),
            )
            if result.returncode == 0:
                status.update(label=f"{label} — done", state="complete")
                if result.stdout.strip():
                    st.code(result.stdout[-3000:])
                if refresh_on_success:
                    st.rerun()
                return True
            status.update(label=f"{label} — failed", state="error")
            st.error(result.stderr.strip() or result.stdout.strip() or f"Exit {result.returncode}")
            return False
        except subprocess.TimeoutExpired:
            status.update(label=f"{label} — timed out", state="error")
            st.error("Timed out after 10 minutes.")
            return False
        except Exception as exc:  # noqa: BLE001
            status.update(label=f"{label} — error", state="error")
            st.error(str(exc))
            return False


def _render_gate_table(report: dict) -> None:
    gate = report.get("validation_gate") or {}
    metrics = gate.get("metrics") or {}
    thresholds = gate.get("thresholds") or {}
    rows = []
    checks = [
        ("Closed Trades", metrics.get("closed_trades"), f"≥ {thresholds.get('min_closed_trades', 30)}",
         metrics.get("closed_trades", 0) >= thresholds.get("min_closed_trades", 30)),
        ("Profit Factor", fmt(metrics.get("profit_factor"), "ratio"), f"≥ {thresholds.get('min_profit_factor', 1.15)}",
         metrics.get("profit_factor", 0) >= thresholds.get("min_profit_factor", 1.15)),
        ("Expectancy", fmt(metrics.get("expectancy"), "money"), f"> ${thresholds.get('min_expectancy', 0)}",
         metrics.get("expectancy", 0) > thresholds.get("min_expectancy", 0)),
        ("Max Drawdown", fmt(metrics.get("max_drawdown"), "percent"), f"≤ {thresholds.get('max_drawdown', 0.08)*100:.0f}%",
         metrics.get("max_drawdown", 1) <= thresholds.get("max_drawdown", 0.08)),
        ("Win Rate", fmt(metrics.get("win_rate"), "percent"), f"≥ {thresholds.get('min_win_rate', 0.4)*100:.0f}%",
         metrics.get("win_rate", 0) >= thresholds.get("min_win_rate", 0.4)),
    ]
    for name, val, req, passed in checks:
        rows.append({"Check": name, "Result": val, "Required": req, "Pass": "✅" if passed else "❌"})
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


st.set_page_config(page_title="Trading Platform", page_icon="📈", layout="wide", initial_sidebar_state="collapsed")
inject_styles()

status = bot_status()
report = load_research_report()
metadata = load_ml_metadata()
predictions = load_ml_predictions()
signals = load_signal_log()
trades = load_trade_log()
labeled = load_labeled_candidates()
ml_summary = ml_filter_summary(metadata, predictions)
backtest = (report or {}).get("backtest", {})
equity_curve = pd.DataFrame((report or {}).get("equity_curve", []))
if not equity_curve.empty and "timestamp" in equity_curve.columns:
    equity_curve["timestamp"] = pd.to_datetime(equity_curve["timestamp"], errors="coerce")

hero(
    "Trading Platform",
    f"Mode: {status['mode']} · Active strategy: {status['strategy']} · "
    f"ML Brain: {'ON' if status['ml_enabled'] else 'OFF'} · "
    f"Live: {'DISABLED' if not status['live_enabled'] else 'ENABLED'}",
)

if status["live_enabled"]:
    st.error("Live trading is enabled — this dashboard is intended for PAPER / SIGNAL_ONLY use.")

with st.expander("⚡ Actions", expanded=False):
    ac1, ac2, ac3, ac4 = st.columns(4)
    if ac1.button("Run Backtest", use_container_width=True):
        _run_command("Running Research Lab backtest", _py_command(
            "research_lab_runner.py", "--strategy", config.ORVWAP_STRATEGY_NAME,
            "--start-date", "2025-09-03", "--end-date", "2026-06-03",
        ), refresh_on_success=True)
    if ac2.button("Train ML Brain", use_container_width=True):
        _run_command("Training ML Brain", _py_command(
            "ml_brain_runner.py", "train", "--start-date", "2025-09-03", "--end-date", "2026-06-03",
        ), refresh_on_success=True)
    if ac3.button("Evaluate Model", use_container_width=True):
        _run_command("Evaluating ML model", _py_command(
            "ml_brain_runner.py", "evaluate", "--start-date", "2025-09-03", "--end-date", "2026-06-03",
        ), refresh_on_success=True)
    if ac4.button("Refresh", use_container_width=True):
        st.rerun()

tab_readme, tab_overview, tab_backtest, tab_ml, tab_trades, tab_risk, tab_advanced = st.tabs(
    ["📖 Read Me", "📊 Overview", "🔬 Backtest", "🧠 ML Brain", "📋 Trades", "🛡️ Safety", "⚙️ Raw Data"]
)

with tab_readme:
    render_readme_page(status=status, report=report, metadata=metadata, ml_summary=ml_summary)

with tab_overview:
    st.markdown("### Performance")
    if report:
        metric_row([
            ("Starting Equity", backtest.get("starting_equity"), "money", ""),
            ("Ending Equity", backtest.get("ending_equity"), "money", ""),
            ("Total Return", backtest.get("total_return"), "percent", "total_return"),
            ("Closed Trades", backtest.get("closed_trades"), "number", "closed_trades"),
        ])
        metric_row([
            ("Win Rate", backtest.get("win_rate"), "percent", "win_rate"),
            ("Profit Factor", backtest.get("profit_factor"), "ratio", "profit_factor"),
            ("Expectancy / Trade", backtest.get("expectancy"), "money", "expectancy"),
            ("Max Drawdown", backtest.get("max_drawdown"), "percent", "max_drawdown"),
        ])
        if not equity_curve.empty and "equity" in equity_curve.columns:
            st.markdown("#### Equity Curve")
            st.line_chart(equity_curve.set_index("timestamp")["equity"], color="#4a9eff")
    else:
        warn_box("No backtest data yet. Expand <strong>Actions</strong> above and click <strong>Run Backtest</strong>.")

    st.markdown("---")
    st.markdown("### ML Brain Filter")
    info_box("ML scores individual trade setups from the <em>active strategy</em>. It does not pick which strategy to run.")
    metric_row([
        ("Threshold", status["ml_threshold"], "number", "ml_score"),
        ("Approved", ml_summary.get("approved_trades"), "number", ""),
        ("Rejected", ml_summary.get("rejected_trades"), "number", ""),
        ("PF After ML", ml_summary.get("pf_after"), "ratio", "profit_factor"),
    ])

with tab_backtest:
    st.markdown("### Backtest Results")
    info_box(
        "A backtest replays historical minute data bar-by-bar, simulates entries/exits with slippage, "
        "then checks if results pass validation gates before allowing paper trading."
    )

    if report is None:
        warn_box("No report yet. Click <strong>Run Backtest</strong> in Actions above.")
    else:
        status_pill(str(report.get("status", "RESEARCH_ONLY")))
        rec = report.get("promotion_recommendation", "")
        if rec:
            st.caption(f"Recommendation: **{rec}**")

        st.markdown("#### Key Numbers")
        metric_row([
            ("Closed Trades", backtest.get("closed_trades"), "number", "closed_trades"),
            ("Win Rate", backtest.get("win_rate"), "percent", "win_rate"),
            ("Profit Factor", backtest.get("profit_factor"), "ratio", "profit_factor"),
            ("Expectancy / Trade", backtest.get("expectancy"), "money", "expectancy"),
            ("Max Drawdown", backtest.get("max_drawdown"), "percent", "max_drawdown"),
            ("Total Return", backtest.get("total_return"), "percent", "total_return"),
        ])

        avg_winner = backtest.get("average_winner")
        avg_loser = backtest.get("average_loser")
        if avg_winner or avg_loser:
            metric_row([
                ("Avg Winner", avg_winner, "money", ""),
                ("Avg Loser", avg_loser, "money", ""),
                ("Best Ticker", backtest.get("best_ticker"), "text", ""),
                ("Worst Ticker", backtest.get("worst_ticker"), "text", ""),
            ])

        st.markdown("#### Validation Gates")
        st.caption("All checks must pass to become a PAPER_CANDIDATE")
        _render_gate_table(report)

        if not equity_curve.empty and "equity" in equity_curve.columns:
            st.markdown("#### Equity Curve")
            st.line_chart(equity_curve.set_index("timestamp")["equity"], color="#3ecf8e")

        symbol_rows = backtest.get("trades_by_symbol", [])
        if symbol_rows:
            st.markdown("#### P&L by Symbol")
            sym_df = pd.DataFrame(symbol_rows).rename(columns={"name": "Symbol", "total_pnl": "Net P&L"})
            sym_df["Net P&L"] = sym_df["Net P&L"].apply(lambda v: fmt(v, "money"))
            st.dataframe(sym_df, use_container_width=True, hide_index=True)

        st.markdown("#### Exports")
        e1, e2 = st.columns(2)
        e1.download_button("Download Report JSON", json.dumps(report, indent=2, default=str),
                           "research_report.json", "application/json", use_container_width=True)
        if not trades.empty:
            e2.download_button("Download Trades CSV", trades.to_csv(index=False),
                               "trades.csv", "text/csv", use_container_width=True)

with tab_ml:
    st.markdown("### ML Trade Brain — Trade Filter")
    info_box(
        "<strong>What ML does:</strong> When the active strategy finds a trade, ML scores it 0–1. "
        f"Scores ≥ {status['ml_threshold']} are allowed; lower scores are rejected.<br>"
        "<strong>What ML does NOT do:</strong> Pick strategies, place orders, or override risk limits."
    )

    metric_row([
        ("Model", status["ml_model_version"], "text", ""),
        ("Fail Closed", "Yes" if status["ml_fail_closed"] else "No", "text", ""),
        ("Good Rejects", ml_summary.get("good_rejects"), "number", ""),
        ("False Rejects", ml_summary.get("false_rejects"), "number", ""),
    ])
    st.markdown("#### Before vs After ML")
    metric_row([
        ("PF Before ML", ml_summary.get("pf_before"), "ratio", "profit_factor"),
        ("PF After ML", ml_summary.get("pf_after"), "ratio", "profit_factor"),
        ("Expectancy Before", ml_summary.get("expectancy_before"), "money", "expectancy"),
        ("Expectancy After", ml_summary.get("expectancy_after"), "money", "expectancy"),
    ])

    if metadata:
        train = metadata.get("train_metrics") or {}
        test = metadata.get("test_metrics") or {}
        st.markdown("#### Training vs Test Split")
        split_df = pd.DataFrame([
            {"Split": "Train", "Rows": metadata.get("train_rows"), "PF Before": fmt(train.get("profit_factor_before_ml"), "ratio"),
             "PF After": fmt(train.get("profit_factor_after_ml"), "ratio"), "Approved": train.get("approved_trade_count")},
            {"Split": "Test", "Rows": metadata.get("test_rows"), "PF Before": fmt(test.get("profit_factor_before_ml"), "ratio"),
             "PF After": fmt(test.get("profit_factor_after_ml"), "ratio"), "Approved": test.get("approved_trade_count")},
        ])
        st.dataframe(split_df, use_container_width=True, hide_index=True)

    if not predictions.empty and "ml_score" in predictions.columns:
        st.markdown("#### Score Distribution")
        st.bar_chart(predictions["ml_score"].dropna())
    elif not metadata:
        warn_box("No model trained yet.")

with tab_trades:
    st.markdown("### Signal & Trade Log")
    table = candidate_trades_table(signals, predictions, trades)
    if table.empty:
        info_box("No signals logged yet. Run a paper cycle or backtest to populate.")
    else:
        st.dataframe(table, use_container_width=True, hide_index=True)
    if not trades.empty:
        st.markdown("#### Executed Trades")
        st.dataframe(trades.tail(100), use_container_width=True, hide_index=True)

with tab_risk:
    st.markdown("### Safety Controls")
    safety = pd.DataFrame([
        {"Setting": "TRADING_MODE", "Value": config.TRADING_MODE, "Meaning": "SIGNAL_ONLY = log only, PAPER = simulated orders"},
        {"Setting": "ENABLE_LIVE_TRADING", "Value": str(config.ENABLE_LIVE_TRADING), "Meaning": "Must be true for real money"},
        {"Setting": "LIVE_ENABLED", "Value": str(config.LIVE_ENABLED), "Meaning": "Second live-trading gate"},
        {"Setting": "GLOBAL_KILL_SWITCH", "Value": str(config.GLOBAL_KILL_SWITCH), "Meaning": "Emergency stop — blocks all trading"},
        {"Setting": "ML_BRAIN_ENABLED", "Value": str(config.ML_BRAIN_ENABLED), "Meaning": "Turn trade filter on/off"},
        {"Setting": "ALLOW_UNVALIDATED_STRATEGY", "Value": str(config.ALLOW_UNVALIDATED_STRATEGY), "Meaning": "Block unvalidated strategies"},
    ])
    st.dataframe(safety, use_container_width=True, hide_index=True)
    if not status["live_enabled"]:
        st.success("Live trading is DISABLED — safe for research and paper mode.")

with tab_advanced:
    st.markdown("### Raw Data (for debugging)")
    with st.expander("Research Lab JSON"):
        st.json(report or {"message": "No report"})
    with st.expander("ML Metadata"):
        st.json(metadata or {"message": "No model"})
    with st.expander("ML Predictions"):
        st.dataframe(predictions if not predictions.empty else pd.DataFrame({"message": ["none"]}))
