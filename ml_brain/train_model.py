"""Train and evaluate ML Trade Brain v1 models."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, precision_score, recall_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

import config
from ml_brain.data_collector import collect_labeled_candidates, labeled_rows_to_dataframe
from ml_brain.feature_builder import NUMERIC_FEATURE_COLUMNS
from ml_brain.registry import DEFAULT_MODEL_VERSION, save_model


def _profit_factor(pnls: pd.Series) -> float:
    wins = pnls[pnls > 0].sum()
    losses = abs(pnls[pnls <= 0].sum())
    if losses == 0:
        return float("inf") if wins > 0 else 0.0
    return float(wins / losses)


def _expectancy(pnls: pd.Series) -> float:
    if pnls.empty:
        return 0.0
    return float(pnls.mean())


def _avg_r(values: pd.Series) -> float:
    clean = pd.to_numeric(values, errors="coerce").dropna()
    if clean.empty:
        return 0.0
    return float(clean.mean())


def time_based_split(df: pd.DataFrame, train_ratio: float = 0.7) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Chronological train/test split — no random shuffle."""
    if df.empty:
        return df.copy(), df.copy()
    ordered = df.copy()
    if "timestamp" in ordered.columns:
        ordered["_sort_ts"] = pd.to_datetime(ordered["timestamp"], errors="coerce", utc=True)
        ordered = ordered.sort_values("_sort_ts").drop(columns=["_sort_ts"])
    split_index = max(1, int(len(ordered) * train_ratio))
    if split_index >= len(ordered):
        split_index = len(ordered) - 1
    return ordered.iloc[:split_index].copy(), ordered.iloc[split_index:].copy()


def walk_forward_folds(df: pd.DataFrame, n_folds: int = 3) -> list[tuple[pd.DataFrame, pd.DataFrame]]:
    """Simple expanding-window walk-forward splits."""
    if len(df) < n_folds + 5:
        train, test = time_based_split(df)
        return [(train, test)]

    ordered = df.copy()
    if "timestamp" in ordered.columns:
        ordered["_sort_ts"] = pd.to_datetime(ordered["timestamp"], errors="coerce", utc=True)
        ordered = ordered.sort_values("_sort_ts").drop(columns=["_sort_ts"])

    folds = []
    min_train = max(10, len(ordered) // (n_folds + 1))
    test_size = max(5, (len(ordered) - min_train) // n_folds)
    for fold in range(n_folds):
        train_end = min_train + fold * test_size
        test_end = min(train_end + test_size, len(ordered))
        if test_end <= train_end:
            break
        folds.append((ordered.iloc[:train_end].copy(), ordered.iloc[train_end:test_end].copy()))
    return folds or [time_based_split(ordered)]


def build_pipeline(model_type: str = "logistic") -> Pipeline:
    if model_type == "random_forest":
        classifier = RandomForestClassifier(
            n_estimators=200,
            max_depth=6,
            random_state=42,
            class_weight="balanced",
        )
    else:
        classifier = LogisticRegression(max_iter=1000, class_weight="balanced", random_state=42)

    return Pipeline(
        steps=[
            ("scaler", StandardScaler()),
            ("classifier", classifier),
        ]
    )


def filter_metrics(
    df: pd.DataFrame,
    approved_mask: pd.Series,
    threshold: float,
) -> dict[str, Any]:
    approved = df[approved_mask]
    rejected = df[~approved_mask]

    approved_wins = approved[approved["label"] == 1] if "label" in approved else approved.iloc[0:0]
    rejected_wins = rejected[rejected["label"] == 1] if "label" in rejected else rejected.iloc[0:0]
    rejected_losses = rejected[rejected["label"] == 0] if "label" in rejected else rejected.iloc[0:0]

    all_pnl = pd.to_numeric(df.get("realized_pnl", pd.Series(dtype=float)), errors="coerce").fillna(0.0)
    approved_pnl = pd.to_numeric(approved.get("realized_pnl", pd.Series(dtype=float)), errors="coerce").fillna(0.0)

    return {
        "threshold": threshold,
        "approved_trade_count": int(len(approved)),
        "rejected_trade_count": int(len(rejected)),
        "approved_trade_win_rate": float((approved["label"] == 1).mean()) if len(approved) else None,
        "false_rejects": int(len(rejected_wins)),
        "good_rejects": int(len(rejected_losses)),
        "profit_factor_before_ml": _profit_factor(all_pnl),
        "profit_factor_after_ml": _profit_factor(approved_pnl) if len(approved) else None,
        "expectancy_before_ml": _expectancy(all_pnl),
        "expectancy_after_ml": _expectancy(approved_pnl) if len(approved) else None,
        "average_r_before_ml": _avg_r(df.get("r_multiple", pd.Series(dtype=float))),
        "average_r_after_ml": _avg_r(approved.get("r_multiple", pd.Series(dtype=float))) if len(approved) else None,
    }


def evaluate_model(pipeline, test_df: pd.DataFrame, threshold: float) -> dict[str, Any]:
    if test_df.empty:
        return {"error": "empty_test_set"}

    x_test = test_df[NUMERIC_FEATURE_COLUMNS].astype(float).fillna(0.0)
    y_test = test_df["label"].astype(int)
    y_pred = pipeline.predict(x_test)
    if hasattr(pipeline, "predict_proba"):
        proba_raw = pipeline.predict_proba(x_test)
        classes = list(getattr(pipeline.named_steps["classifier"], "classes_", [0, 1]))
        if 1 in classes:
            proba = proba_raw[:, classes.index(1)]
        else:
            proba = proba_raw[:, -1]
    else:
        proba = y_pred.astype(float)

    approved_mask = proba >= threshold
    metrics = {
        "accuracy": float(accuracy_score(y_test, y_pred)),
        "precision": float(precision_score(y_test, y_pred, zero_division=0)),
        "recall": float(recall_score(y_test, y_pred, zero_division=0)),
    }
    metrics.update(filter_metrics(test_df.assign(_score=proba), approved_mask, threshold))
    return metrics


def train_model(
    labeled_df: pd.DataFrame,
    model_type: str = "logistic",
    threshold: float | None = None,
) -> dict[str, Any]:
    threshold = float(threshold if threshold is not None else config.ML_THRESHOLD_DEFAULT)
    if labeled_df.empty:
        raise ValueError("No labeled rows available for training.")

    labeled_df = labeled_df.dropna(subset=["label"]).copy()
    if len(labeled_df) < int(config.ML_MIN_TRADE_COUNT_FOR_MODEL):
        raise ValueError(
            f"Need at least {config.ML_MIN_TRADE_COUNT_FOR_MODEL} labeled candidates, "
            f"got {len(labeled_df)}."
        )

    train_df, test_df = time_based_split(labeled_df)
    x_train = train_df[NUMERIC_FEATURE_COLUMNS].astype(float).fillna(0.0)
    y_train = train_df["label"].astype(int)

    pipeline = build_pipeline(model_type)
    pipeline.fit(x_train, y_train)

    train_metrics = evaluate_model(pipeline, train_df, threshold)
    test_metrics = evaluate_model(pipeline, test_df, threshold)

    wf_results = []
    for fold_index, (wf_train, wf_test) in enumerate(walk_forward_folds(labeled_df)):
        if wf_test.empty or wf_train.empty:
            continue
        fold_pipeline = build_pipeline(model_type)
        fold_pipeline.fit(
            wf_train[NUMERIC_FEATURE_COLUMNS].astype(float).fillna(0.0),
            wf_train["label"].astype(int),
        )
        wf_results.append(
            {"fold": fold_index, **evaluate_model(fold_pipeline, wf_test, threshold)}
        )

    metadata = {
        "model_version": DEFAULT_MODEL_VERSION,
        "model_type": model_type,
        "threshold": threshold,
        "feature_columns": NUMERIC_FEATURE_COLUMNS,
        "train_rows": len(train_df),
        "test_rows": len(test_df),
        "train_metrics": train_metrics,
        "test_metrics": test_metrics,
        "walk_forward": wf_results,
        "trained_at": datetime.now(timezone.utc).isoformat(),
    }

    artifact_path = save_model(pipeline, metadata)
    metadata["artifact_path"] = str(artifact_path)
    return metadata


def train_from_backtest(
    symbols: list[str],
    start_date: str,
    end_date: str,
    model_type: str = "logistic",
    threshold: float | None = None,
    data_dir: str = "historical_data",
) -> dict[str, Any]:
    rows = collect_labeled_candidates(symbols, start_date, end_date, data_dir=data_dir)
    df = labeled_rows_to_dataframe(rows)
    csv_path = Path(getattr(config, "ML_LABELED_DATA_PATH", "logs/ml_labeled_candidates.csv"))
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(csv_path, index=False)
    result = train_model(df, model_type=model_type, threshold=threshold)
    result["labeled_csv"] = str(csv_path)
    result["labeled_rows"] = len(df)
    return result


def save_evaluation_report(report: dict, output_dir: str = "research_results/ml_brain") -> str:
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    path = Path(output_dir) / f"evaluation_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
    with open(path, "w", encoding="utf-8") as file:
        json.dump(report, file, indent=2, default=str)
    return str(path)
