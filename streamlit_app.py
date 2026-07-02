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
    load_multi_strategy_report,
    load_ml_predictions,
    load_research_report,
    load_signal_log,
    load_trade_log,
    ml_filter_summary,
)


def _metric(value, kind="number"):
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "n/a"
    if kind == "money":
        return f"${float(value):,.2f}"
    if kind == "percent":
        return f"{float(value) * 100:.2f}%"
    return f"{float(value):.2f}"


def _py_command(script: str, *args: str) -> list[str]:
    return python_command(script, *args)


def _run_command(label: str, command: list[str], *, refresh_on_success: bool = False) -> bool:
    with st.status(label, expanded=True) as status:
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=False,
                timeout=600,
                cwd=PROJECT_ROOT,
                env=command_env(),
            )
            if result.returncode == 0:
                status.update(label=f"{label} — done", state="complete")
                if result.stdout.strip():
                    st.code(result.stdout[-4000:])
                if refresh_on_success:
                    st.success("Done — refreshing dashboard.")
                    st.rerun()
                return True

            status.update(label=f"{label} — failed", state="error")
            st.error(result.stderr.strip() or result.stdout.strip() or f"Exit code {result.returncode}")
            return False
        except subprocess.TimeoutExpired:
            status.update(label=f"{label} — timed out", state="error")
            st.error("Command timed out after 10 minutes.")
            return False
        except Exception as exc:  # noqa: BLE001
            status.update(label=f"{label} — error", state="error")
            st.error(str(exc))
            return False


st.set_page_config(page_title="Trading Platform", page_icon="📈", layout="wide")
st.title("Trading Platform Dashboard")

status = bot_status()
header_cols = st.columns(5)
header_cols[0].metric("Mode", "PAPER" if status["mode"] != "LIVE" else status["mode"])
header_cols[1].metric("Strategy", status["strategy"])
header_cols[2].metric("ML Brain", "ON" if status["ml_enabled"] else "OFF")
header_cols[3].metric("Model", status["ml_model_version"])
header_cols[4].metric("Live Trading", "DISABLED" if not status["live_enabled"] else "ENABLED")

if status["live_enabled"]:
    st.error("Live trading flag is enabled in config — this dashboard is intended for PAPER / SIGNAL_ONLY use.")

action_cols = st.columns(5)
if action_cols[0].button("Run Backtest", use_container_width=True):
    _run_command(
        "Running Research Lab backtest",
        _py_command(
            "research_lab_runner.py",
            "--strategy",
            config.ORVWAP_STRATEGY_NAME,
            "--start-date",
            "2025-09-03",
            "--end-date",
            "2026-06-03",
        ),
        refresh_on_success=True,
    )
if action_cols[1].button("Train ML Brain", use_container_width=True):
    _run_command(
        "Training ML Trade Brain v1",
        _py_command(
            "ml_brain_runner.py",
            "train",
            "--start-date",
            "2025-09-03",
            "--end-date",
            "2026-06-03",
        ),
        refresh_on_success=True,
    )
if action_cols[2].button("Evaluate Model", use_container_width=True):
    _run_command(
        "Evaluating ML model",
        _py_command(
            "ml_brain_runner.py",
            "evaluate",
            "--start-date",
            "2025-09-03",
            "--end-date",
            "2026-06-03",
        ),
        refresh_on_success=True,
    )
if action_cols[3].button("Run Multi-Strategy", use_container_width=True):
    _run_command(
        "Running multi-strategy research comparison",
        _py_command(
            "multi_strategy_research_runner.py",
            "--start-date",
            "2025-09-03",
            "--end-date",
            "2026-06-03",
        ),
        refresh_on_success=True,
    )
if action_cols[4].button("Refresh Dashboard", use_container_width=True):
    st.rerun()

report = load_research_report()
multi_strategy = load_multi_strategy_report()
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

tab_overview, tab_backtest, tab_allocator, tab_ml, tab_trades, tab_risk, tab_advanced = st.tabs(
    ["Overview", "Backtest Results", "Strategy Allocator", "ML Brain", "Trades", "Risk & Safety", "Advanced JSON"]
)

with tab_overview:
    st.subheader("Performance Snapshot")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Starting Equity", _metric(backtest.get("starting_equity"), "money"))
    c2.metric("Ending Equity", _metric(backtest.get("ending_equity"), "money"))
    c3.metric("Total Return", _metric(backtest.get("total_return"), "percent"))
    c4.metric("Closed Trades", backtest.get("closed_trades", "n/a"))

    c5, c6, c7, c8 = st.columns(4)
    c5.metric("Win Rate", _metric(backtest.get("win_rate"), "percent"))
    c6.metric("Profit Factor", _metric(backtest.get("profit_factor")))
    c7.metric("Expectancy", _metric(backtest.get("expectancy"), "money"))
    c8.metric("Max Drawdown", _metric(backtest.get("max_drawdown"), "percent"))

    st.subheader("ML Brain Snapshot")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Threshold", status["ml_threshold"])
    m2.metric("Approved (log)", ml_summary.get("approved_trades", "n/a"))
    m3.metric("Rejected (log)", ml_summary.get("rejected_trades", "n/a"))
    m4.metric("PF After ML", _metric(ml_summary.get("pf_after")))

    if not equity_curve.empty and "equity" in equity_curve.columns:
        st.line_chart(equity_curve.set_index("timestamp")["equity"])

with tab_backtest:
    if report is None:
        st.info("No Research Lab report yet. Use **Run Backtest** to generate one.")
    else:
        st.json(
            {
                "status": report.get("status"),
                "recommendation": report.get("promotion_recommendation"),
                "backtest": report.get("backtest"),
            }
        )
        if not equity_curve.empty:
            st.subheader("Equity Curve")
            st.line_chart(equity_curve.set_index("timestamp")["equity"])
        symbol_rows = backtest.get("trades_by_symbol", [])
        if symbol_rows:
            st.subheader("Symbol Performance")
            st.bar_chart(pd.DataFrame(symbol_rows).set_index("name")["total_pnl"])

        export_col1, export_col2 = st.columns(2)
        export_col1.download_button(
            "Export Results JSON",
            data=json.dumps(report, indent=2, default=str),
            file_name="research_report.json",
            mime="application/json",
            use_container_width=True,
        )
        if not trades.empty:
            export_col2.download_button(
                "Export Trade Log CSV",
                data=trades.to_csv(index=False),
                file_name="trades.csv",
                mime="text/csv",
                use_container_width=True,
            )

with tab_allocator:
    st.subheader("Multi-Strategy Research")
    if multi_strategy is None:
        st.info("No multi-strategy comparison yet. Use **Run Multi-Strategy** to generate one.")
    else:
        allocator = multi_strategy.get("strategy_allocator", {})
        summary = multi_strategy.get("summary", {})
        a1, a2, a3, a4 = st.columns(4)
        a1.metric("Allocator Mode", allocator.get("mode", "n/a"))
        a2.metric("Top Strategy", summary.get("top_strategy", "n/a"))
        a3.metric("Strategies Tested", summary.get("strategies_tested", "n/a"))
        a4.metric("Strategies Skipped", summary.get("strategies_skipped", "n/a"))
        st.caption(allocator.get("reason", "Research-only guidance."))

        leaderboard = pd.DataFrame(multi_strategy.get("leaderboard", []))
        if not leaderboard.empty:
            st.subheader("Leaderboard")
            display_cols = [
                column
                for column in [
                    "rank",
                    "strategy_name",
                    "score",
                    "closed_trades",
                    "profit_factor",
                    "expectancy",
                    "total_return",
                    "max_drawdown",
                    "recommendation",
                ]
                if column in leaderboard.columns
            ]
            st.dataframe(leaderboard[display_cols], use_container_width=True)

        by_regime = pd.DataFrame(multi_strategy.get("best_by_regime", []))
        if not by_regime.empty:
            st.subheader("Best Strategy By Regime")
            st.dataframe(by_regime[["regime", "recommended_strategy", "reason"]], use_container_width=True)

        if multi_strategy.get("skipped"):
            with st.expander("Skipped Strategies"):
                st.json(multi_strategy["skipped"])

with tab_ml:
    st.subheader("ML Trade Brain v1")
    st.caption("Filter/scorer only — ML never submits orders. Risk engine remains final authority.")

    ml1, ml2, ml3, ml4 = st.columns(4)
    ml1.metric("Model Version", status["ml_model_version"])
    ml2.metric("Fail Closed", "Yes" if status["ml_fail_closed"] else "No")
    ml3.metric("Good Rejects", ml_summary.get("good_rejects", "n/a"))
    ml4.metric("False Rejects", ml_summary.get("false_rejects", "n/a"))

    ml5, ml6, ml7, ml8 = st.columns(4)
    ml5.metric("PF Before ML", _metric(ml_summary.get("pf_before")))
    ml6.metric("PF After ML", _metric(ml_summary.get("pf_after")))
    ml7.metric("Expectancy Before", _metric(ml_summary.get("expectancy_before"), "money"))
    ml8.metric("Expectancy After", _metric(ml_summary.get("expectancy_after"), "money"))

    if metadata:
        with st.expander("Latest training metrics"):
            st.json(metadata.get("test_metrics", {}))

    if not predictions.empty and "ml_score" in predictions.columns:
        st.subheader("ML Score Distribution")
        st.bar_chart(predictions["ml_score"].dropna())
        st.subheader("Approved vs Rejected")
        counts = predictions["ml_decision"].value_counts()
        st.bar_chart(counts)
    else:
        st.info("No ML predictions logged yet. Enable ML_BRAIN_ENABLED and run paper cycles or backtests.")

    if not labeled.empty:
        st.subheader("Labeled Training Rows")
        st.dataframe(labeled.tail(100), use_container_width=True)

with tab_trades:
    table = candidate_trades_table(signals, predictions, trades)
    if table.empty:
        st.info("No candidate trades in signal log yet.")
    else:
        st.dataframe(table, use_container_width=True)
    if not trades.empty:
        st.subheader("Executed Trades")
        st.dataframe(trades.tail(100), use_container_width=True)

with tab_risk:
    st.subheader("Safety Status")
    st.write(
        {
            "TRADING_MODE": config.TRADING_MODE,
            "AUTO_STRATEGY_SELECTION": config.AUTO_STRATEGY_SELECTION,
            "AUTO_STRATEGY_USE_SHADOW_LEADER": config.AUTO_STRATEGY_USE_SHADOW_LEADER,
            "ENABLE_LIVE_TRADING": config.ENABLE_LIVE_TRADING,
            "LIVE_ENABLED": config.LIVE_ENABLED,
            "GLOBAL_KILL_SWITCH": config.GLOBAL_KILL_SWITCH,
            "ML_BRAIN_ENABLED": config.ML_BRAIN_ENABLED,
            "ML_FAIL_CLOSED": config.ML_FAIL_CLOSED,
            "ALLOW_UNVALIDATED_STRATEGY": config.ALLOW_UNVALIDATED_STRATEGY,
        }
    )
    st.warning("Reset Paper State is not implemented in this repo — button intentionally omitted for safety.")
    st.caption("Paper positions live in portfolio/positions.csv and broker reconciliation must stay in sync.")

with tab_advanced:
    with st.expander("Research Lab JSON"):
        st.json(report or {"message": "No report loaded"})
    with st.expander("Multi-Strategy JSON"):
        st.json(multi_strategy or {"message": "No multi-strategy report loaded"})
    with st.expander("ML Metadata JSON"):
        st.json(metadata or {"message": "No model trained"})
    with st.expander("Raw ML Predictions"):
        st.dataframe(predictions, use_container_width=True)
