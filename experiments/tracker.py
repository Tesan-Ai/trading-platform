from __future__ import annotations

import csv
import json
import math
import os
from datetime import datetime, timezone
from uuid import uuid4

from database.repositories import save_experiment


SUMMARY_FIELDS = [
    "run_id",
    "created_at",
    "strategy",
    "stage",
    "status",
    "passes_gate",
    "start_date",
    "end_date",
    "symbols",
    "closed_trades",
    "win_rate",
    "profit_factor",
    "expectancy",
    "max_drawdown",
    "total_pnl",
    "output_path",
]


def record_experiment(
    strategy_name: str,
    report: dict,
    gate: dict,
    parameters: dict | None = None,
    output_dir: str = "research_results/experiments",
) -> str:
    os.makedirs(output_dir, exist_ok=True)
    run_id = _run_id(strategy_name)
    created_at = datetime.now(timezone.utc).isoformat()
    parameters = parameters or {}

    payload = {
        "run_id": run_id,
        "created_at": created_at,
        "strategy": strategy_name,
        "parameters": parameters,
        "report": _json_safe(report),
        "validation_gate": _json_safe(gate),
    }

    output_path = os.path.join(output_dir, f"{run_id}.json")
    with open(output_path, "w", encoding="utf-8") as file:
        json.dump(payload, file, indent=2)

    _append_summary(output_dir, output_path, payload)
    save_experiment(payload)
    return output_path


def _append_summary(output_dir: str, output_path: str, payload: dict) -> None:
    summary_path = os.path.join(output_dir, "experiment_summary.csv")
    report = payload["report"]
    gate = payload["validation_gate"]
    parameters = payload["parameters"]
    row = {
        "run_id": payload["run_id"],
        "created_at": payload["created_at"],
        "strategy": payload["strategy"],
        "stage": gate.get("stage"),
        "status": gate.get("status"),
        "passes_gate": gate.get("passes"),
        "start_date": parameters.get("start_date"),
        "end_date": parameters.get("end_date"),
        "symbols": ",".join(parameters.get("symbols", [])),
        "closed_trades": report.get("closed_trades"),
        "win_rate": report.get("win_rate"),
        "profit_factor": report.get("profit_factor"),
        "expectancy": report.get("expectancy"),
        "max_drawdown": report.get("max_drawdown"),
        "total_pnl": report.get("total_pnl"),
        "output_path": output_path,
    }

    write_header = not os.path.exists(summary_path)
    with open(summary_path, "a", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=SUMMARY_FIELDS)
        if write_header:
            writer.writeheader()
        writer.writerow(row)


def _run_id(strategy_name: str) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    slug = "".join(char if char.isalnum() else "_" for char in strategy_name.lower()).strip("_")
    return f"{timestamp}_{slug}_{uuid4().hex[:8]}"


def _json_safe(value):
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if hasattr(value, "item"):
        try:
            return _json_safe(value.item())
        except (TypeError, ValueError):
            pass
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, float):
        if math.isnan(value):
            return None
        if math.isinf(value):
            return "Infinity" if value > 0 else "-Infinity"
    return value
