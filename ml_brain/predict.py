"""ML Trade Brain v1 inference — filter/scorer only."""

from __future__ import annotations

from typing import Any

import numpy as np

import config
from ml_brain.feature_builder import NUMERIC_FEATURE_COLUMNS, build_feature_row, feature_vector
from ml_brain.registry import DEFAULT_MODEL_VERSION, load_metadata, load_model, model_exists


def _human_reasons(feature_row: dict, importances: dict | None = None) -> list[str]:
    reasons: list[str] = []
    if feature_row.get("relative_volume", 0) >= 1.5:
        reasons.append("Strong relative volume")
    if feature_row.get("vwap_distance", 0) > 0:
        reasons.append("Price above VWAP")
    if feature_row.get("qqq_trend", 0) >= 1.0:
        reasons.append("QQQ trend confirmed")
    if feature_row.get("spy_trend", 0) >= 1.0:
        reasons.append("SPY trend confirmed")
    if feature_row.get("breakout_strength", 0) > 0:
        reasons.append("Opening range breakout strength")

    if importances:
        ranked = sorted(importances.items(), key=lambda item: abs(item[1]), reverse=True)
        for name, _weight in ranked[:3]:
            pretty = name.replace("_", " ").title()
            if pretty not in reasons:
                reasons.append(pretty)

    return reasons[:5] or ["Model score above threshold"]


def _feature_importance_map(model) -> dict | None:
    try:
        classifier = model.named_steps["classifier"]
        if hasattr(classifier, "feature_importances_"):
            return {
                name: float(value)
                for name, value in zip(NUMERIC_FEATURE_COLUMNS, classifier.feature_importances_)
            }
        if hasattr(classifier, "coef_"):
            coef = classifier.coef_[0]
            return {name: float(value) for name, value in zip(NUMERIC_FEATURE_COLUMNS, coef)}
    except (AttributeError, KeyError, IndexError, TypeError):
        return None
    return None


def predict_trade(
    candidate_trade: dict,
    features: dict | None = None,
    regime: dict | None = None,
    threshold: float | None = None,
) -> dict[str, Any]:
    """Score a candidate trade. Never places orders.

    Returns dict with ml_score, decision (ALLOW/REJECT), threshold, model_version,
    top_reasons, and error info when prediction fails.
    """
    threshold = float(threshold if threshold is not None else config.ML_THRESHOLD_DEFAULT)
    version = DEFAULT_MODEL_VERSION
    feature_row = build_feature_row(candidate_trade, features=features, regime=regime)

    base_response = {
        "ml_score": None,
        "decision": "REJECT",
        "threshold": threshold,
        "model_version": version,
        "top_reasons": [],
        "feature_row": feature_row,
        "error": None,
    }

    if not getattr(config, "ML_BRAIN_ENABLED", False):
        base_response["decision"] = "ALLOW"
        base_response["ml_score"] = 1.0
        base_response["top_reasons"] = ["ML brain disabled — pass-through"]
        return base_response

    if not model_exists():
        base_response["error"] = "model_not_found"
        if getattr(config, "ML_FAIL_CLOSED", True):
            base_response["top_reasons"] = ["Model missing — fail closed"]
            return base_response
        base_response["decision"] = "ALLOW"
        base_response["ml_score"] = 1.0
        base_response["top_reasons"] = ["Model missing — fail open (ML_FAIL_CLOSED=false)"]
        return base_response

    try:
        pipeline = load_model()
        metadata = load_metadata()
        version = metadata.get("model_version", version)
        vector = np.array([feature_vector(feature_row)])
        if hasattr(pipeline, "predict_proba"):
            proba = pipeline.predict_proba(vector)[0]
            classes = list(getattr(pipeline.named_steps["classifier"], "classes_", [0, 1]))
            if 1 in classes:
                score = float(proba[classes.index(1)])
            else:
                score = float(proba[-1])
        else:
            score = float(pipeline.predict(vector)[0])

        decision = "ALLOW" if score >= threshold else "REJECT"
        importances = _feature_importance_map(pipeline)
        return {
            "ml_score": round(score, 4),
            "decision": decision,
            "threshold": threshold,
            "model_version": version,
            "top_reasons": _human_reasons(feature_row, importances),
            "feature_row": feature_row,
            "error": None,
        }
    except Exception as exc:  # noqa: BLE001 — fail-closed filter must not crash trading loop
        base_response["error"] = str(exc)
        if getattr(config, "ML_FAIL_CLOSED", True):
            base_response["top_reasons"] = ["Prediction failed — fail closed"]
            return base_response
        base_response["decision"] = "ALLOW"
        base_response["ml_score"] = 1.0
        base_response["top_reasons"] = ["Prediction failed — fail open"]
        return base_response
