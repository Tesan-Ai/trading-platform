import csv
import os
from datetime import datetime

TRADE_LOG_FILE = "data/trades.csv"


def ensure_trade_log_file():
    if not os.path.exists(TRADE_LOG_FILE):
        with open(TRADE_LOG_FILE, "w", newline="") as file:
            writer = csv.writer(file)
            writer.writerow([
                "timestamp",
                "symbol",
                "action",
                "shares",
                "price",
                "position_value",
                "score",
                "pnl",
                "reason"
            ])


def log_trade(action, symbol, price, shares, position_value, score, pnl=0.0, reason=""):
    ensure_trade_log_file()

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with open(TRADE_LOG_FILE, "a", newline="") as file:
        writer = csv.writer(file)
        writer.writerow([
            timestamp,
            symbol,
            action,
            int(shares),
            round(float(price), 2),
            round(float(position_value), 2),
            round(float(score), 2),
            round(float(pnl), 2),
            reason
        ])


def load_trade_log():
    ensure_trade_log_file()

    trades = []

    with open(TRADE_LOG_FILE, "r", newline="") as file:
        reader = csv.DictReader(file)

        for row in reader:
            trades.append(row)

    return trades
