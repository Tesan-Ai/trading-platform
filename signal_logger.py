import csv
import os
from datetime import datetime

import config
from database.repositories import save_signal

SIGNAL_FIELDS = [
    "timestamp",
    "ticker",
    "mode",
    "price",
    "opening_range_high",
    "opening_range_low",
    "vwap",
    "current_volume",
    "volume_avg_20",
    "volume_ratio",
    "atr",
    "distance_from_vwap",
    "distance_from_vwap_atr",
    "spread",
    "entry_approved",
    "rejection_reason",
    "entry_price",
    "stop_price",
    "target_price",
    "position_size",
    "exit_price",
    "exit_reason",
    "realized_pnl",
    "account_equity",
    "strategy_version",
    "spy_above_vwap",
    "qqq_above_vwap",
    "market_filter_reason",
    "event_type",
]


def ensure_signal_log_file(log_file: str | None = None) -> str:
    path = log_file or config.ORVWAP_SIGNAL_LOG_FILE
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)

    if not os.path.exists(path):
        with open(path, "w", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=SIGNAL_FIELDS)
            writer.writeheader()

    return path


def log_signal(event_type: str, payload: dict, log_file: str | None = None) -> None:
    path = ensure_signal_log_file(log_file)
    row = {field: payload.get(field) for field in SIGNAL_FIELDS}
    row["event_type"] = event_type
    if row.get("timestamp") is None:
        row["timestamp"] = datetime.now().isoformat()

    with open(path, "a", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=SIGNAL_FIELDS)
        writer.writerow(row)

    save_signal(event_type, row)


def summarize_rejections(log_file: str | None = None) -> dict[str, int]:
    path = ensure_signal_log_file(log_file)
    counts: dict[str, int] = {}

    if not os.path.exists(path):
        return counts

    with open(path, "r", newline="") as file:
        reader = csv.DictReader(file)
        for row in reader:
            if row.get("entry_approved") in {"True", "true", "1"}:
                continue
            reason = row.get("rejection_reason") or "unknown"
            counts[reason] = counts.get(reason, 0) + 1

    return counts
