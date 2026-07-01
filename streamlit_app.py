import json
from pathlib import Path

import pandas as pd
import streamlit as st

import config


EXPERIMENT_SUMMARY = Path("research_results/experiments/experiment_summary.csv")
RESEARCH_LAB_SUMMARY = Path("research_results/research_lab/research_lab_summary.csv")
SIGNAL_LOG = Path("logs/orvwap_signals.csv")


def load_latest_research_lab_report(summary_path: Path = RESEARCH_LAB_SUMMARY) -> dict | None:
    if not summary_path.exists():
        return None
    summary = pd.read_csv(summary_path)
    if summary.empty or "json_path" not in summary:
        return None
    latest = summary.sort_values("created_at").iloc[-1]
    json_path = Path(str(latest["json_path"]))
    if not json_path.exists():
        return None
    with open(json_path, "r", encoding="utf-8") as file:
        return json.load(file)


def warning_messages(report: dict | None, supabase_enabled: bool) -> list[str]:
    warnings = []
    if report is None:
        warnings.append("No Research Lab report found yet.")
        return warnings
    backtest = report.get("backtest", {})
    thresholds = report.get("validation_gate", {}).get("thresholds", {})
    if int(backtest.get("closed_trades", 0) or 0) < int(thresholds.get("min_closed_trades", 30)):
        warnings.append("Closed trades are below the validation threshold.")
    if float(backtest.get("profit_factor", 0.0) or 0.0) < float(thresholds.get("min_profit_factor", 1.15)):
        warnings.append("Profit factor fails the validation threshold.")
    if float(backtest.get("expectancy", 0.0) or 0.0) <= float(thresholds.get("min_expectancy", 0.0)):
        warnings.append("Expectancy is not positive enough for promotion.")
    if float(backtest.get("max_drawdown", 0.0) or 0.0) > float(thresholds.get("max_drawdown", 0.08)):
        warnings.append("Max drawdown exceeds the validation threshold.")
    if not supabase_enabled:
        warnings.append("Supabase is not configured or is disabled.")
    warnings.append("Live trading is disabled, which is expected.")
    return warnings


def _metric_value(value, kind: str = "number") -> str:
    if value is None:
        return "n/a"
    if kind == "money":
        return f"${float(value):,.2f}"
    if kind == "percent":
        return f"{float(value) * 100:.2f}%"
    return f"{float(value):.2f}"


st.set_page_config(page_title="Trading Platform", layout="wide")
st.title("Trading Platform")

research_report = load_latest_research_lab_report()
st.header("Research Lab")
if research_report is None:
    st.info("No Research Lab report found yet. Run research_lab_runner.py to create one.")
else:
    backtest = research_report.get("backtest", {})
    monte_carlo = research_report.get("monte_carlo", {})
    st.subheader(research_report.get("strategy_name", "Unknown strategy"))
    status_col, recommendation_col = st.columns(2)
    status_col.metric("Strategy Status", research_report.get("status", "UNKNOWN"))
    recommendation_col.metric(
        "Recommendation",
        research_report.get("promotion_recommendation", {}).get("recommendation", "UNKNOWN"),
    )

    col1, col2, col3, col4, col5, col6 = st.columns(6)
    col1.metric("Total Return", _metric_value(backtest.get("total_return"), "percent"))
    col2.metric("Profit Factor", _metric_value(backtest.get("profit_factor")))
    col3.metric("Expectancy", _metric_value(backtest.get("expectancy"), "money"))
    col4.metric("Win Rate", _metric_value(backtest.get("win_rate"), "percent"))
    col5.metric("Max Drawdown", _metric_value(backtest.get("max_drawdown"), "percent"))
    col6.metric("MC Loss Prob", _metric_value(monte_carlo.get("probability_of_loss"), "percent"))

    warnings = warning_messages(research_report, bool(config.SUPABASE_ENABLED))
    for message in warnings:
        st.warning(message)

    equity_curve = pd.DataFrame(research_report.get("equity_curve", []))
    if not equity_curve.empty:
        equity_curve["timestamp"] = pd.to_datetime(equity_curve["timestamp"])
        st.subheader("Equity Curve")
        st.line_chart(equity_curve.set_index("timestamp")["equity"])
        st.subheader("Drawdown")
        st.line_chart(equity_curve.set_index("timestamp")["drawdown"])

    st.subheader("Trades by Symbol")
    st.dataframe(pd.DataFrame(backtest.get("trades_by_symbol", [])), use_container_width=True)

    st.subheader("Performance by Regime")
    st.dataframe(
        pd.DataFrame(research_report.get("market_regime", {}).get("performance_by_regime", [])),
        use_container_width=True,
    )

if RESEARCH_LAB_SUMMARY.exists():
    st.subheader("Recent Research Lab Runs")
    lab_summary = pd.read_csv(RESEARCH_LAB_SUMMARY)
    st.dataframe(lab_summary.sort_values("created_at", ascending=False), use_container_width=True)

if EXPERIMENT_SUMMARY.exists():
    st.header("Walk-Forward Experiments")
    experiments = pd.read_csv(EXPERIMENT_SUMMARY)
    latest = experiments.iloc[-1]
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Latest Status", latest.get("status", "UNKNOWN"))
    col2.metric("Profit Factor", f"{float(latest.get('profit_factor', 0.0)):.2f}")
    col3.metric("Expectancy", f"${float(latest.get('expectancy', 0.0)):.2f}")
    col4.metric("Closed Trades", int(latest.get("closed_trades", 0)))

    st.subheader("Experiment History")
    st.dataframe(experiments.sort_values("created_at", ascending=False), use_container_width=True)
else:
    st.info("No experiment summary found yet. Run walk_forward_runner.py to create one.")

if SIGNAL_LOG.exists():
    st.subheader("Recent OR/VWAP Signals")
    signals = pd.read_csv(SIGNAL_LOG)
    st.dataframe(signals.tail(100), use_container_width=True)
