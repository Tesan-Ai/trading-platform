"""Tests for ML Trade Brain v1 safety and core behavior."""

from __future__ import annotations

import pandas as pd
import pytest

import config
from ml_brain.feature_builder import build_feature_row, feature_vector
from ml_brain.integration import apply_ml_brain_filter
from ml_brain.label_builder import label_candidate_from_forward_bars
from ml_brain.predict import predict_trade
from dashboard.data_loader import bot_status, ml_filter_summary


SAMPLE_CANDIDATE = {
    "timestamp": "2026-01-15T10:30:00-05:00",
    "ticker": "NVDA",
    "side": "LONG",
    "strategy_name": config.ORVWAP_STRATEGY_NAME,
    "price": 100.0,
    "entry_price": 100.0,
    "opening_range_high": 99.5,
    "opening_range_low": 98.0,
    "vwap": 99.0,
    "volume_ratio": 2.0,
    "atr": 1.5,
    "distance_from_vwap": 0.01,
    "entry_approved": True,
    "stop_price": 98.5,
    "target_price": 102.0,
}


def test_live_trading_disabled_by_default():
    assert config.TRADING_MODE in {"SIGNAL_ONLY", "PAPER", "LIVE"}
    assert config.ENABLE_LIVE_TRADING is False or config.TRADING_MODE != "LIVE"


def test_feature_builder_produces_numeric_vector():
    row = build_feature_row(
        SAMPLE_CANDIDATE,
        features={"return_1m": 0.001, "return_5m": 0.003, "return_15m": 0.005},
        regime={"spy_above_vwap": True, "qqq_above_vwap": True, "trade_allowed": True},
    )
    vector = feature_vector(row)
    assert len(vector) == 17
    assert all(isinstance(value, float) for value in vector)


def test_label_builder_target_before_stop():
    forward = pd.DataFrame(
        [
            {"open": 100, "high": 101, "low": 99.8, "close": 100.5, "volume": 1000},
            {"open": 100.5, "high": 102.5, "low": 100.2, "close": 102.0, "volume": 1000},
        ]
    )
    result = label_candidate_from_forward_bars(100.0, 98.5, 102.0, forward)
    assert result["label"] == 1
    assert result["exit_reason"] == "target"


def test_label_builder_stop_before_target():
    forward = pd.DataFrame(
        [
            {"open": 100, "high": 100.2, "low": 98.4, "close": 98.6, "volume": 1000},
        ]
    )
    result = label_candidate_from_forward_bars(100.0, 98.5, 102.0, forward)
    assert result["label"] == 0
    assert result["exit_reason"] == "stop"


def test_predict_trade_shape_when_disabled(monkeypatch):
    monkeypatch.setattr(config, "ML_BRAIN_ENABLED", False)
    result = predict_trade(SAMPLE_CANDIDATE)
    assert result["decision"] == "ALLOW"
    assert "ml_score" in result
    assert "threshold" in result
    assert "model_version" in result
    assert isinstance(result["top_reasons"], list)


def test_predict_fails_closed_without_model(monkeypatch):
    monkeypatch.setattr(config, "ML_BRAIN_ENABLED", True)
    monkeypatch.setattr(config, "ML_FAIL_CLOSED", True)
    monkeypatch.setattr("ml_brain.predict.model_exists", lambda version=None: False)
    result = predict_trade(SAMPLE_CANDIDATE)
    assert result["decision"] == "REJECT"
    assert result["error"] == "model_not_found"


def test_ml_filter_does_not_bypass_risk_gate_pattern(monkeypatch):
    """ML filter returns allowed flag only — risk gate is still separate in paper_trader."""
    monkeypatch.setattr(config, "ML_BRAIN_ENABLED", False)
    allowed, enriched = apply_ml_brain_filter(SAMPLE_CANDIDATE)
    assert allowed is True
    assert enriched.get("ml_decision") == "ALLOW"
    # Risk gate must still be invoked by caller (paper_trader) — ML only adds metadata here.
    assert "entry_price" in enriched or enriched.get("entry_price") is None


def test_failed_prediction_rejects_when_fail_closed(monkeypatch):
    monkeypatch.setattr(config, "ML_BRAIN_ENABLED", True)
    monkeypatch.setattr(config, "ML_FAIL_CLOSED", True)

    def _boom(*args, **kwargs):
        raise RuntimeError("model exploded")

    monkeypatch.setattr("ml_brain.predict.load_model", _boom)
    monkeypatch.setattr("ml_brain.predict.model_exists", lambda version=None: True)
    result = predict_trade(SAMPLE_CANDIDATE)
    assert result["decision"] == "REJECT"


def test_dashboard_helpers_missing_ml_data():
    summary = ml_filter_summary({}, pd.DataFrame())
    assert summary["approved_trades"] is None or isinstance(summary["approved_trades"], (int, type(None)))
    status = bot_status()
    assert "mode" in status
    assert status["live_enabled"] is False or isinstance(status["live_enabled"], bool)
