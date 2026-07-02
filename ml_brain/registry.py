"""Model artifact registry for ML Trade Brain v1."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib

import config

DEFAULT_MODEL_VERSION = "ml_trade_brain_v1"
DEFAULT_MODEL_DIR = Path("models/ml_trade_brain_v1")


def model_dir(version: str | None = None) -> Path:
    version = version or DEFAULT_MODEL_VERSION
    return Path(getattr(config, "ML_MODEL_DIR", f"models/{version}"))


def model_path(version: str | None = None) -> Path:
    configured = getattr(config, "ML_MODEL_PATH", None)
    if configured and version is None:
        return Path(configured)
    return model_dir(version) / "model.joblib"


def metadata_path(version: str | None = None) -> Path:
    return model_dir(version) / "metadata.json"


def save_model(
    pipeline,
    metadata: dict[str, Any],
    version: str | None = None,
) -> Path:
    directory = model_dir(version)
    directory.mkdir(parents=True, exist_ok=True)
    artifact_path = directory / "model.joblib"
    joblib.dump(pipeline, artifact_path)

    meta = dict(metadata)
    meta.setdefault("model_version", version or DEFAULT_MODEL_VERSION)
    meta["saved_at"] = datetime.now(timezone.utc).isoformat()
    meta_path = directory / "metadata.json"
    with open(meta_path, "w", encoding="utf-8") as file:
        json.dump(meta, file, indent=2)

    runs_dir = Path(getattr(config, "ML_RUNS_DIR", "research_results/ml_brain"))
    runs_dir.mkdir(parents=True, exist_ok=True)
    run_file = runs_dir / f"model_run_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
    with open(run_file, "w", encoding="utf-8") as file:
        json.dump(meta, file, indent=2)

    return artifact_path


def load_model(version: str | None = None):
    path = model_path(version)
    if not path.exists():
        raise FileNotFoundError(f"ML model not found at {path}")
    return joblib.load(path)


def load_metadata(version: str | None = None) -> dict:
    path = metadata_path(version)
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as file:
        return json.load(file)


def active_model_version() -> str:
    meta = load_metadata()
    return meta.get("model_version", DEFAULT_MODEL_VERSION)


def model_exists(version: str | None = None) -> bool:
    return model_path(version).exists()
