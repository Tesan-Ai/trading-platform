"""Partner-facing Read Me page for the Streamlit dashboard."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st

import config
from dashboard.ui_components import (
    fmt,
    hero,
    info_box,
    inject_styles,
    metric_row,
    status_pill,
    success_box,
    warn_box,
)
from strategies.factory import STRATEGY_REGISTRY


STRATEGY_CATALOG = [
    {
        "id": "opening_range_vwap_momentum_v1",
        "name": "Opening Range VWAP Momentum",
        "role": "Primary — paper trading focus",
        "status": "Active candidate",
        "idea": "Buy mega-caps breaking above their 5-min opening range, above VWAP, with volume while SPY/QQQ align.",
        "window": "09:35–10:30 ET entry, flat by 15:55",
        "symbols": ", ".join(config.ORVWAP_TRADE_SYMBOLS),
    },
    {
        "id": "orb_pullback_continuation_v1",
        "name": "ORB Pullback Continuation",
        "role": "Research only",
        "status": "RESEARCH ONLY",
        "idea": "Don't buy the breakout candle. Wait for pullback, enter on break of pullback high.",
        "window": "15-min OR, scale-out at 1R, trail runner",
        "symbols": ", ".join(config.ORB_PBC_SYMBOLS),
    },
    {
        "id": "momentum_breakout_v1",
        "name": "Momentum Breakout",
        "role": "Research sweeps",
        "status": "Failed on ETFs",
        "idea": "Breakout + EMA alignment + RVOL + RSI filters. Tested 128 ETF configs — none profitable.",
        "window": "Intraday, 2:1 R/R",
        "symbols": "ETF universe (SPY, QQQ, sectors)",
    },
    {
        "id": "daily_trend_v1",
        "name": "Daily Trend",
        "role": "Secondary",
        "status": "Paper-capable",
        "idea": "Swing trades following daily trend. Holds overnight.",
        "window": "Multi-day holds, 8% stop / 50% target",
        "symbols": "Configurable universe",
    },
    {
        "id": "bull_day_trade_v1",
        "name": "Bull Day Trade",
        "role": "Legacy research",
        "status": "Research sweeps",
        "idea": "Intraday momentum with ATR stop and 2R target.",
        "window": "Intraday only",
        "symbols": "Configurable universe",
    },
    {
        "id": "momentum_scan_v1",
        "name": "Momentum Scan (Legacy)",
        "role": "Legacy live path",
        "status": "Deprecated path",
        "idea": "Scans Alpaca universe with rule-based scoring (ai_model.py). Separate from modern replay.",
        "window": "Full market scan",
        "symbols": "Broad US equities",
    },
]


def load_orb_pbc_latest() -> dict | None:
    summary_path = Path("research_results/orb_pbc_v1/orb_pbc_summary.csv")
    if not summary_path.exists():
        return None
    frame = pd.read_csv(summary_path)
    if frame.empty:
        return None
    baseline = frame[frame["profile"] == "baseline"]
    source = baseline if not baseline.empty else frame
    return source.sort_values("created_at").iloc[-1].to_dict()


def render_readme_page(*, status: dict, report: dict | None, metadata: dict, ml_summary: dict) -> None:
    inject_styles()
    orb_pbc = load_orb_pbc_latest()
    backtest = (report or {}).get("backtest", {})
    active = status.get("strategy", config.ACTIVE_STRATEGY)

    hero(
        "How This Platform Works",
        "Evidence-driven trading: test on history → validate → paper trade → (gated) live. "
        "Live trading is off by default.",
    )

    # ── Critical clarification ──
    st.markdown("### How Strategies & AI Actually Work")
    info_box(
        "<strong>One strategy runs at a time.</strong> Right now the active strategy is "
        f"<code>{active}</code> (set in your .env as ACTIVE_STRATEGY). "
        "The bot does <em>not</em> switch between strategies automatically."
    )
    info_box(
        "<strong>ML Brain is a trade filter, not a strategy picker.</strong> Flow: "
        "Active strategy finds a trade → ML scores that specific setup (0–1) → "
        "if score ≥ threshold, allow → risk checks → execute. "
        "ML never chooses <em>which</em> strategy to run."
    )
    warn_box(
        "<strong>ai_model.py</strong> is a separate rule-based scorer used only by the legacy "
        "momentum_scan path. It is not an AI that picks between strategies."
    )

    st.markdown("---")
    st.markdown("### All Strategies in the Codebase")
    st.caption(f"{len(STRATEGY_REGISTRY)} strategies registered · 1 active · rest are research or legacy")

    for s in STRATEGY_CATALOG:
        is_active = s["id"] == active
        border = "🟢" if is_active else ("🔬" if "RESEARCH" in s["status"] else "⚪")
        with st.expander(f"{border} **{s['name']}** — {s['status']}", expanded=is_active):
            c1, c2 = st.columns([1, 2])
            with c1:
                st.markdown(f"**ID:** `{s['id']}`")
                st.markdown(f"**Role:** {s['role']}")
                st.markdown(f"**Symbols:** {s['symbols']}")
                if is_active:
                    success_box("This is the strategy currently running in paper/signal mode.")
            with c2:
                st.markdown(f"**Logic:** {s['idea']}")
                st.markdown(f"**Timing:** {s['window']}")

    st.markdown("---")
    st.markdown("### Platform Status")
    metric_row([
        ("Mode", status.get("mode"), "text", ""),
        ("Active Strategy", active, "text", ""),
        ("ML Brain", "ON" if status.get("ml_enabled") else "OFF", "text", ""),
        ("Live Trading", "OFF" if not status.get("live_enabled") else "ON", "text", ""),
    ])

    st.markdown("---")
    st.markdown("### Promotion Pipeline")
    steps = st.columns(5)
    for col, (num, title, desc) in zip(
        steps,
        [
            ("1", "Research", "Backtest on historical minute data"),
            ("2", "Validate", "Walk-forward + pass/fail gates"),
            ("3", "Paper", "Alpaca paper account"),
            ("4", "Reconcile", "Local CSV vs broker sync"),
            ("5", "Live", "Explicitly gated — off now"),
        ],
    ):
        with col:
            st.markdown(f"**{num}. {title}**")
            st.caption(desc)

    st.markdown("---")
    st.markdown("### Latest Results")

    r1, r2, r3 = st.tabs(["Primary (OR/VWAP)", "ORB Pullback (Research)", "ML Brain Filter"])

    with r1:
        if report:
            status_pill(str(report.get("status", "RESEARCH_ONLY")))
            metric_row([
                ("Closed Trades", backtest.get("closed_trades"), "number", "closed_trades"),
                ("Win Rate", backtest.get("win_rate"), "percent", "win_rate"),
                ("Profit Factor", backtest.get("profit_factor"), "ratio", "profit_factor"),
                ("Expectancy", backtest.get("expectancy"), "money", "expectancy"),
                ("Max Drawdown", backtest.get("max_drawdown"), "percent", "max_drawdown"),
                ("Total Return", backtest.get("total_return"), "percent", "total_return"),
            ])
        else:
            warn_box("No backtest run yet. Click <strong>Run Backtest</strong> at the top of the dashboard.")

    with r2:
        if orb_pbc:
            status_pill(str(orb_pbc.get("status", "RESEARCH_ONLY")))
            metric_row([
                ("Closed Trades", orb_pbc.get("closed_trades"), "number", "closed_trades"),
                ("Win Rate", orb_pbc.get("win_rate"), "percent", "win_rate"),
                ("Profit Factor", orb_pbc.get("profit_factor_after_costs"), "ratio", "profit_factor"),
                ("Expectancy", orb_pbc.get("expectancy"), "money", "expectancy"),
                ("Max Drawdown", orb_pbc.get("max_drawdown"), "percent", "max_drawdown"),
            ])
            warn_box(
                f"Strong per-trade stats but only {int(orb_pbc.get('closed_trades', 0))} trades — "
                "needs more history before promotion. Not active for paper trading."
            )
        else:
            info_box("No ORB-PBC results yet.")

    with r3:
        if metadata:
            train = metadata.get("train_metrics") or {}
            test = metadata.get("test_metrics") or {}
            metric_row([
                ("Train Rows", metadata.get("train_rows"), "number", ""),
                ("Test Rows", metadata.get("test_rows"), "number", ""),
                ("PF Before ML", train.get("profit_factor_before_ml"), "ratio", "profit_factor"),
                ("PF After ML", train.get("profit_factor_after_ml"), "ratio", "profit_factor"),
            ])
            warn_box(
                f"Only {metadata.get('train_rows', 0)} training examples — too small to trust in production. "
                "ML filters individual trades from the active strategy; it does not pick strategies."
            )
        else:
            info_box("No ML model trained yet. Click <strong>Train ML Brain</strong> at the top.")

    st.markdown("---")
    st.markdown("### Dashboard Tour")
    tour = pd.DataFrame([
        {"Tab": "Overview", "What you'll see": "Equity curve + key performance numbers"},
        {"Tab": "Backtest Results", "What you'll see": "Human-readable backtest report with pass/fail gates"},
        {"Tab": "ML Brain", "What you'll see": "How the trade filter performs before vs after ML"},
        {"Tab": "Trades", "What you'll see": "Every signal, ML decision, and executed trade"},
        {"Tab": "Risk & Safety", "What you'll see": "Confirms live trading is disabled"},
    ])
    st.dataframe(tour, use_container_width=True, hide_index=True)

    with st.expander("Export platform snapshot"):
        st.download_button(
            "Download JSON",
            data=json.dumps({"status": status, "orb_pbc": orb_pbc, "report_status": (report or {}).get("status")}, indent=2, default=str),
            file_name="platform_snapshot.json",
            mime="application/json",
        )
