import csv
import os
from datetime import datetime

import config
from portfolio_manager import load_open_positions
from ai_model import score_stock

EQUITY_FILE = "data/equity_curve.csv"


def ensure_equity_file():
    os.makedirs(os.path.dirname(EQUITY_FILE), exist_ok=True)

    if not os.path.exists(EQUITY_FILE):
        with open(EQUITY_FILE, "w", newline="") as file:
            writer = csv.writer(file)
            writer.writerow([
                "timestamp",
                "equity",
                "cash_balance",
                "open_position_value",
                "unrealized_pnl"
            ])


def calculate_open_position_value():
    positions = load_open_positions()
    total_position_value = 0.0

    for position in positions:
        shares = float(position["shares"])
        entry_price = float(position["entry_price"])
        symbol = position["symbol"]

        stock_result = score_stock(symbol)

        if stock_result is not None:
            current_price = float(stock_result["close"])
        else:
            current_price = entry_price

        total_position_value += shares * current_price

    return total_position_value


def calculate_unrealized_pnl():
    positions = load_open_positions()
    total_unrealized_pnl = 0.0

    for position in positions:
        shares = float(position["shares"])
        entry_price = float(position["entry_price"])
        symbol = position["symbol"]

        stock_result = score_stock(symbol)

        if stock_result is not None:
            current_price = float(stock_result["close"])
        else:
            current_price = entry_price

        total_unrealized_pnl += (current_price - entry_price) * shares

    return total_unrealized_pnl


def calculate_cash_balance():
    positions = load_open_positions()
    invested_cost_basis = 0.0

    for position in positions:
        shares = float(position["shares"])
        entry_price = float(position["entry_price"])
        invested_cost_basis += shares * entry_price

    return float(config.INITIAL_CAPITAL) - invested_cost_basis


def calculate_equity():
    cash_balance = calculate_cash_balance()
    open_position_value = calculate_open_position_value()
    return cash_balance + open_position_value


def record_equity():
    ensure_equity_file()

    equity = calculate_equity()
    cash_balance = calculate_cash_balance()
    open_position_value = calculate_open_position_value()
    unrealized_pnl = calculate_unrealized_pnl()
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with open(EQUITY_FILE, "a", newline="") as file:
        writer = csv.writer(file)
        writer.writerow([
            timestamp,
            round(equity, 2),
            round(cash_balance, 2),
            round(open_position_value, 2),
            round(unrealized_pnl, 2)
        ])
