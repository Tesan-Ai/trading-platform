"""Shared Streamlit UI styling and metric helpers."""

from __future__ import annotations

import pandas as pd
import streamlit as st


METRIC_HELP = {
    "profit_factor": "Gross wins ÷ gross losses. Above 1.0 = profitable. Gate: ≥ 1.15.",
    "win_rate": "Percentage of trades that made money.",
    "expectancy": "Average dollars earned (or lost) per trade.",
    "max_drawdown": "Worst peak-to-trough decline in account equity.",
    "closed_trades": "Total completed trades — more trades = more reliable stats.",
    "total_return": "Overall gain or loss on starting capital.",
    "avg_r": "Average reward-to-risk ratio per trade (how much you make vs how much you risk).",
    "sharpe": "Risk-adjusted return. Higher is better.",
    "ml_score": "ML confidence (0–1) that this specific trade will hit target before stop.",
}


def inject_styles() -> None:
    st.markdown(
        """
        <style>
        .block-container { padding-top: 1.5rem; max-width: 1200px; }
        div[data-testid="stMetric"] {
            background: linear-gradient(135deg, #1a1f2e 0%, #232938 100%);
            border: 1px solid #2d3548;
            border-radius: 12px;
            padding: 14px 16px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.18);
        }
        div[data-testid="stMetric"] label {
            color: #8b95a8 !important;
            font-size: 0.78rem !important;
            text-transform: uppercase;
            letter-spacing: 0.04em;
        }
        div[data-testid="stMetric"] [data-testid="stMetricValue"] {
            color: #f0f3f7 !important;
            font-size: 1.55rem !important;
            font-weight: 700 !important;
        }
        .hero-box {
            background: linear-gradient(120deg, #1e3a5f 0%, #2d1b4e 100%);
            border-radius: 14px;
            padding: 22px 26px;
            margin-bottom: 1.2rem;
            border: 1px solid #3d4f6f;
        }
        .hero-box h1 { color: #fff; margin: 0 0 6px 0; font-size: 1.6rem; }
        .hero-box p { color: #c8d4e8; margin: 0; font-size: 0.95rem; line-height: 1.5; }
        .info-card {
            background: #1e2433;
            border-left: 4px solid #4a9eff;
            border-radius: 0 10px 10px 0;
            padding: 14px 18px;
            margin: 10px 0;
            color: #d0d8e8;
            font-size: 0.92rem;
        }
        .warn-card {
            background: #2a2218;
            border-left: 4px solid #f0a030;
            border-radius: 0 10px 10px 0;
            padding: 14px 18px;
            margin: 10px 0;
            color: #f0dcc0;
            font-size: 0.92rem;
        }
        .success-card {
            background: #182a22;
            border-left: 4px solid #3ecf8e;
            border-radius: 0 10px 10px 0;
            padding: 14px 18px;
            margin: 10px 0;
            color: #c8f0dc;
            font-size: 0.92rem;
        }
        .section-label {
            color: #6b7891;
            font-size: 0.72rem;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            margin-bottom: 0.4rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def hero(title: str, subtitle: str) -> None:
    st.markdown(
        f'<div class="hero-box"><h1>{title}</h1><p>{subtitle}</p></div>',
        unsafe_allow_html=True,
    )


def info_box(text: str) -> None:
    st.markdown(f'<div class="info-card">{text}</div>', unsafe_allow_html=True)


def warn_box(text: str) -> None:
    st.markdown(f'<div class="warn-card">{text}</div>', unsafe_allow_html=True)


def success_box(text: str) -> None:
    st.markdown(f'<div class="success-card">{text}</div>', unsafe_allow_html=True)


def fmt(value, kind="number"):
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "—"
    if kind == "text":
        return str(value)
    if kind == "money":
        v = float(value)
        sign = "+" if v >= 0 else ""
        return f"{sign}${v:,.2f}"
    if kind == "percent":
        return f"{float(value) * 100:.1f}%"
    if kind == "ratio":
        return f"{float(value):.2f}x"
    return f"{float(value):.2f}"


def metric_row(items: list[tuple[str, object, str, str]]) -> None:
    """Render a row of metrics: (label, value, kind, help_key)."""
    cols = st.columns(len(items))
    for col, (label, value, kind, help_key) in zip(cols, items):
        with col:
            display = fmt(value, kind) if kind != "number" or _is_numeric(value) else str(value)
            st.metric(label, display, help=METRIC_HELP.get(help_key, ""))


def _is_numeric(value) -> bool:
    try:
        float(value)
        return True
    except (TypeError, ValueError):
        return False


def status_pill(status: str) -> None:
    s = (status or "UNKNOWN").upper()
    if s in {"PAPER_CANDIDATE", "LIVE_CANDIDATE"}:
        success_box(f"Status: <strong>{s.replace('_', ' ')}</strong> — passed validation gate")
    elif s == "RESEARCH_ONLY":
        warn_box(f"Status: <strong>RESEARCH ONLY</strong> — still being tested, not live-ready")
    else:
        info_box(f"Status: <strong>{s.replace('_', ' ')}</strong>")
