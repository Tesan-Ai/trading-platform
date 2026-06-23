import csv
import os

TRADE_LOG_FILE = "data/trades.csv"


def load_trades():
    trades = []

    if not os.path.exists(TRADE_LOG_FILE):
        return trades

    with open(TRADE_LOG_FILE, mode="r", newline="") as file:
        reader = csv.DictReader(file)

        for row in reader:
            row["shares"] = int(row["shares"])
            row["price"] = float(row["price"])
            row["position_value"] = float(row["position_value"])
            row["score"] = float(row["score"])
            row["pnl"] = float(row["pnl"])
            trades.append(row)

    return trades


def calculate_performance():
    trades = load_trades()

    sell_trades = []

    for trade in trades:
        if trade["action"] == "SELL":
            sell_trades.append(trade)

    total_trades = len(sell_trades)
    total_pnl = 0.0
    winning_trades = 0
    losing_trades = 0
    total_win_amount = 0.0
    total_loss_amount = 0.0
    best_trade = None
    worst_trade = None

    for trade in sell_trades:
        pnl = trade["pnl"]
        total_pnl += pnl

        if best_trade is None or pnl > best_trade["pnl"]:
            best_trade = trade

        if worst_trade is None or pnl < worst_trade["pnl"]:
            worst_trade = trade

        if pnl > 0:
            winning_trades += 1
            total_win_amount += pnl
        elif pnl < 0:
            losing_trades += 1
            total_loss_amount += pnl

    win_rate = 0.0
    if total_trades > 0:
        win_rate = (winning_trades / total_trades) * 100

    average_win = 0.0
    if winning_trades > 0:
        average_win = total_win_amount / winning_trades

    average_loss = 0.0
    if losing_trades > 0:
        average_loss = total_loss_amount / losing_trades

    return {
        "total_trades": total_trades,
        "winning_trades": winning_trades,
        "losing_trades": losing_trades,
        "win_rate": win_rate,
        "total_pnl": total_pnl,
        "average_win": average_win,
        "average_loss": average_loss,
        "best_trade": best_trade,
        "worst_trade": worst_trade
    }


def print_performance_summary():
    stats = calculate_performance()

    print("\nBOT PERFORMANCE")
    print("-------------------")
    print("Closed Trades:", stats["total_trades"])
    print("Winning Trades:", stats["winning_trades"])
    print("Losing Trades:", stats["losing_trades"])
    print(f'Win Rate: {stats["win_rate"]:.2f}%')
    print(f'Total P/L: ${stats["total_pnl"]:.2f}')
    print(f'Average Win: ${stats["average_win"]:.2f}')
    print(f'Average Loss: ${stats["average_loss"]:.2f}')

    if stats["best_trade"] is not None:
        print(
            f'Best Trade: {stats["best_trade"]["symbol"]} '
            f'${stats["best_trade"]["pnl"]:.2f}'
        )

    if stats["worst_trade"] is not None:
        print(
            f'Worst Trade: {stats["worst_trade"]["symbol"]} '
            f'${stats["worst_trade"]["pnl"]:.2f}'
        )
