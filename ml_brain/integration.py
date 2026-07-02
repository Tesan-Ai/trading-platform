"""Integration helpers — ML filter sits between strategy and risk/execution."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import config
from ml_brain.predict import predict_trade


def apply_ml_brain_filter(
    candidate_trade: dict,
    features: dict | None = None,
    regime: dict | None = None,
) -> tuple[bool, dict[str, Any]]:
    """Return (allowed, prediction_dict).

    When ML_BRAIN_ENABLED=false, always allows (pass-through).
    ML never bypasses risk checks — caller must still call RiskGate.can_trade().
    """
    prediction = predict_trade(candidate_trade, features=features, regime=regime)
    allowed = prediction.get("decision") == "ALLOW"

    enriched = dict(candidate_trade)
    enriched["ml_score"] = prediction.get("ml_score")
    enriched["ml_decision"] = prediction.get("decision")
    enriched["ml_threshold"] = prediction.get("threshold")
    enriched["ml_model_version"] = prediction.get("model_version")
    enriched["ml_top_reasons"] = prediction.get("top_reasons")
    enriched["ml_error"] = prediction.get("error")

    if not allowed and not enriched.get("rejection_reason"):
        enriched["rejection_reason"] = "ML brain rejected trade"
        enriched["entry_approved"] = False

    return allowed, enriched


def log_ml_prediction(prediction: dict, candidate: dict) -> None:
    """Append ML prediction to local CSV log."""
    if not getattr(config, "ML_BRAIN_ENABLED", False):
        return
    import csv
    import os

    path = getattr(config, "ML_PREDICTION_LOG_FILE", "logs/ml_predictions.csv")
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    fields = [
        "timestamp",
        "symbol",
        "strategy_name",
        "ml_score",
        "ml_decision",
        "ml_threshold",
        "model_version",
        "top_reasons",
        "error",
        "entry_price",
        "final_action",
    ]
    write_header = not os.path.exists(path)
    row = {
        "timestamp": datetime.now().isoformat(),
        "symbol": candidate.get("ticker") or candidate.get("symbol"),
        "strategy_name": candidate.get("strategy_name") or candidate.get("strategy_version"),
        "ml_score": prediction.get("ml_score"),
        "ml_decision": prediction.get("decision"),
        "ml_threshold": prediction.get("threshold"),
        "model_version": prediction.get("model_version"),
        "top_reasons": "|".join(prediction.get("top_reasons") or []),
        "error": prediction.get("error"),
        "entry_price": candidate.get("entry_price"),
        "final_action": "BLOCKED" if prediction.get("decision") == "REJECT" else "ALLOWED",
    }
    with open(path, "a", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        if write_header:
            writer.writeheader()
        writer.writerow(row)

    try:
        from database.repositories import save_ml_prediction

        save_ml_prediction(row)
    except Exception:
        pass
