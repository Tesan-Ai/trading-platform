import csv
import os
from datetime import datetime
from zoneinfo import ZoneInfo

EASTERN = ZoneInfo("America/New_York")

POSITIONS_FILE = "portfolio/positions.csv"
POSITION_FIELDS = [
    "symbol",
    "entry_price",
    "shares",
    "entry_score",
    "entry_timestamp",
    "status"
]


def ensure_positions_file():
    os.makedirs(os.path.dirname(POSITIONS_FILE), exist_ok=True)

    if not os.path.exists(POSITIONS_FILE):
        with open(POSITIONS_FILE, "w", newline="") as file:
            writer = csv.writer(file)
            writer.writerow(POSITION_FIELDS)


def load_all_positions():
    ensure_positions_file()
    positions = []

    with open(POSITIONS_FILE, "r", newline="") as file:
        reader = csv.DictReader(file)

        for row in reader:
            row["entry_price"] = float(row["entry_price"])
            row["shares"] = int(row["shares"])
            row["entry_score"] = float(row["entry_score"])
            positions.append(row)

    return positions


def load_open_positions():
    positions = load_all_positions()
    open_positions = []

    for row in positions:
        if row["status"] == "OPEN":
            open_positions.append(row)

    return open_positions


def _normalize_timestamp(current_time=None):
    if current_time is None:
        current_time = datetime.now(EASTERN)
    elif current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=EASTERN)
    else:
        current_time = current_time.astimezone(EASTERN)

    return current_time.strftime("%Y-%m-%d %H:%M:%S")


def add_position(symbol, entry_price, shares, entry_score, current_time=None):
    ensure_positions_file()

    with open(POSITIONS_FILE, "a", newline="") as file:
        writer = csv.writer(file)
        writer.writerow([
            symbol,
            round(float(entry_price), 4),
            int(shares),
            round(float(entry_score), 4),
            _normalize_timestamp(current_time),
            "OPEN"
        ])


def close_position(symbol):
    positions = load_all_positions()
    updated = False

    for row in positions:
        if row["symbol"] == symbol and row["status"] == "OPEN":
            row["status"] = "CLOSED"
            updated = True
            break

    if not updated:
        return False

    with open(POSITIONS_FILE, "w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=POSITION_FIELDS)
        writer.writeheader()

        for row in positions:
            writer.writerow({
                "symbol": row["symbol"],
                "entry_price": row["entry_price"],
                "shares": row["shares"],
                "entry_score": row["entry_score"],
                "entry_timestamp": row["entry_timestamp"],
                "status": row["status"]
            })

    return True


def count_open_positions():
    return len(load_open_positions())
