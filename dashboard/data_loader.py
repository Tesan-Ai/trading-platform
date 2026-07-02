"""Dashboard data loaders — safe when ML artifacts or reports are missing."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

import config


def load_research_report() -> dict | None:
    summary = Path("research_results/research_lab/research_lab_summary.csv")
    if not summary.exists():
        return None
    frame = pd.read_csv(summary)
    if frame.empty:
        return None
    latest = frame.sort_values("created_at").iloc[-1]
    json_path = Path(str(latest["json_path"]))
    if not json_path.exists():
        return None
    with open(json_path, "r", encoding="utf-8") as file:
        return json.load(file)


def load_ml_metadata() -> dict:
    path = Path(config.ML_MODEL_DIR) / "metadata.json"
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as file:
        return json.load(file)


def load_ml_predictions() -> pd.DataFrame:
    path = Path(config.ML_PREDICTION_LOG_FILE)
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path)


def load_signal_log() -> pd.DataFrame:
    path = Path(config.ORVWAP_SIGNAL_LOG_FILE)
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path)


def load_trade_log() -> pd.DataFrame:
    path = Path("data/trades.csv")
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path)


def load_labeled_candidates() -> pd.DataFrame:
    path = Path(config.ML_LABELED_DATA_PATH)
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path)


def ml_filter_summary(metadata: dict, predictions: pd.DataFrame) -> dict:
    test_metrics = metadata.get("test_metrics") or {}
    if predictions.empty:
        return {
            "approved_trades": test_metrics.get("approved_trade_count"),
            "rejected_trades": test_metrics.get("rejected_trade_count"),
            "good_rejects": test_metrics.get("good_rejects"),
            "false_rejects": test_metrics.get("false_rejects"),
            "pf_before": test_metrics.get("profit_factor_before_ml"),
            "pf_after": test_metrics.get("profit_factor_after_ml"),
            "expectancy_before": test_metrics.get("expectancy_before_ml"),
            "expectancy_after": test_metrics.get("expectancy_after_ml"),
        }

    approved = predictions[predictions["ml_decision"].isin(["ALLOW", "ALLOWED"])]
    rejected = predictions[predictions["ml_decision"] == "REJECT"]
    return {
        "approved_trades": len(approved),
        "rejected_trades": len(rejected),
        "good_rejects": test_metrics.get("good_rejects"),
        "false_rejects": test_metrics.get("false_rejects"),
        "pf_before": test_metrics.get("profit_factor_before_ml"),
        "pf_after": test_metrics.get("profit_factor_after_ml"),
        "expectancy_before": test_metrics.get("expectancy_before_ml"),
        "expectancy_after": test_metrics.get("expectancy_after_ml"),
    }


def candidate_trades_table(signals: pd.DataFrame, predictions: pd.DataFrame, trades: pd.DataFrame) -> pd.DataFrame:
    if signals.empty:
        return pd.DataFrame()

    frame = signals.copy()
    if "ml_score" not in frame.columns and not predictions.empty:
        pred = predictions.copy()
        pred["symbol"] = pred["symbol"]
        frame = frame.merge(
            pred[["symbol", "ml_score", "ml_decision", "model_version"]],
            left_on="ticker",
            right_on="symbol",
            how="left",
            suffixes=("", "_ml"),
        )

    frame["risk_decision"] = frame.get("entry_approved", False).map(lambda v: "ALLOW" if str(v) in {"True", "true", "1"} else "REJECT")
    frame["final_action"] = frame.apply(
        lambda row: "EXECUTED" if row.get("event_type") == "ENTRY" else ("BLOCKED" if row.get("ml_decision") == "REJECT" else "SIGNAL"),
        axis=1,
    )
    cols = [
        c
        for c in [
            "timestamp",
            "ticker",
            "event_type",
            "entry_approved",
            "ml_score",
            "ml_decision",
            "risk_decision",
            "final_action",
            "realized_pnl",
            "rejection_reason",
            "volume_ratio",
        ]
        if c in frame.columns
    ]
    return frame[cols].tail(200)


def bot_status() -> dict:
    metadata = load_ml_metadata()
    return {
        "mode": config.TRADING_MODE,
        "live_enabled": bool(config.ENABLE_LIVE_TRADING or config.LIVE_ENABLED),
        "strategy": config.ACTIVE_STRATEGY,
        "ml_enabled": bool(config.ML_BRAIN_ENABLED),
        "ml_threshold": config.ML_THRESHOLD_DEFAULT,
        "ml_model_version": metadata.get("model_version", "not trained"),
        "ml_fail_closed": bool(config.ML_FAIL_CLOSED),
        "supabase_enabled": bool(config.SUPABASE_ENABLED),
    }
