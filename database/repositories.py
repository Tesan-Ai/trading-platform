from __future__ import annotations

from datetime import date, datetime

import config
from database.supabase_client import get_supabase_client


def save_experiment(payload: dict) -> None:
    if not _enabled():
        return
    gate = payload.get("validation_gate", {})
    parameters = payload.get("parameters", {})
    report = payload.get("report", {})
    row = {
        "run_id": payload.get("run_id"),
        "created_at": payload.get("created_at"),
        "strategy": payload.get("strategy"),
        "stage": gate.get("stage"),
        "status": gate.get("status"),
        "passes_gate": gate.get("passes"),
        "start_date": parameters.get("start_date"),
        "end_date": parameters.get("end_date"),
        "symbols": parameters.get("symbols", []),
        "report": report,
        "validation_gate": gate,
        "parameters": parameters,
    }
    _insert("experiments", row)


def save_signal(event_type: str, payload: dict) -> None:
    if not _enabled():
        return
    row = {
        "event_timestamp": _iso_or_none(payload.get("timestamp")),
        "strategy": payload.get("strategy_version") or payload.get("strategy_name") or "unknown",
        "symbol": payload.get("ticker") or payload.get("symbol"),
        "mode": payload.get("mode") or config.TRADING_MODE,
        "event_type": event_type,
        "entry_approved": bool(payload.get("entry_approved", False)),
        "rejection_reason": payload.get("rejection_reason"),
        "price": payload.get("price"),
        "stop_price": payload.get("stop_price"),
        "target_price": payload.get("target_price"),
        "payload": _json_safe(payload),
    }
    _insert("signals", row)


def save_order(row: dict) -> None:
    if not _enabled():
        return
    _insert("orders", _json_safe(row))


def save_positions(broker: str, positions: list[dict]) -> None:
    if not _enabled():
        return
    client = get_supabase_client()
    if client is None:
        return
    for position in positions:
        row = {
            "broker": broker,
            "symbol": position.get("symbol"),
            "quantity": position.get("quantity"),
            "average_entry_price": position.get("average_entry_price"),
            "market_value": position.get("market_value"),
            "payload": _json_safe(position),
        }
        client.table("positions").upsert(row, on_conflict="broker,symbol").execute()


def save_risk_event(
    event_type: str,
    message: str,
    severity: str = "INFO",
    strategy: str | None = None,
    payload: dict | None = None,
) -> None:
    if not _enabled():
        return
    row = {
        "strategy": strategy,
        "severity": severity,
        "event_type": event_type,
        "message": message,
        "payload": _json_safe(payload or {}),
    }
    _insert("risk_events", row)


def save_research_report(report: dict) -> None:
    if not _enabled():
        return
    row = {
        "strategy_name": report.get("strategy_name"),
        "start_date": report.get("start_date"),
        "end_date": report.get("end_date"),
        "profile": report.get("profile"),
        "status": report.get("status"),
        "total_return": _numeric_or_none(report.get("backtest", {}).get("total_return")),
        "profit_factor": _numeric_or_none(report.get("backtest", {}).get("profit_factor")),
        "expectancy": _numeric_or_none(report.get("backtest", {}).get("expectancy")),
        "win_rate": _numeric_or_none(report.get("backtest", {}).get("win_rate")),
        "max_drawdown": _numeric_or_none(report.get("backtest", {}).get("max_drawdown")),
        "monte_carlo_probability_of_loss": _numeric_or_none(
            report.get("monte_carlo", {}).get("probability_of_loss")
        ),
        "recommendation": report.get("promotion_recommendation", {}).get("recommendation"),
        "report_json": _json_safe(report),
    }
    _insert("research_reports", row)


def save_ml_prediction(row: dict) -> None:
    if not _enabled():
        return
    payload = {
        "event_timestamp": _iso_or_none(row.get("timestamp")),
        "strategy": row.get("strategy_name"),
        "symbol": row.get("symbol"),
        "ml_score": _numeric_or_none(row.get("ml_score")),
        "ml_decision": row.get("ml_decision") or row.get("final_action"),
        "ml_threshold": _numeric_or_none(row.get("ml_threshold")),
        "model_version": row.get("model_version"),
        "top_reasons": row.get("top_reasons"),
        "error": row.get("error"),
        "payload": _json_safe(row),
    }
    _insert("ml_predictions", payload)


def save_model_run(report: dict) -> None:
    if not _enabled():
        return
    row = {
        "run_id": report.get("run_id") or report.get("trained_at"),
        "model_version": report.get("model_version"),
        "model_type": report.get("model_type"),
        "status": report.get("status", "completed"),
        "train_rows": report.get("train_rows"),
        "test_rows": report.get("test_rows"),
        "report": _json_safe(report),
    }
    _insert("model_runs", row)


def _insert(table: str, row: dict) -> None:
    client = get_supabase_client()
    if client is None:
        return
    try:
        client.table(table).insert(_json_safe(row)).execute()
    except Exception:
        return


def _enabled() -> bool:
    return bool(getattr(config, "SUPABASE_ENABLED", False))


def _iso_or_none(value):
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _json_safe(value):
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if hasattr(value, "item"):
        try:
            return _json_safe(value.item())
        except (TypeError, ValueError):
            pass
    return value


def _numeric_or_none(value):
    if value in {None, "", "Infinity", "-Infinity"}:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
