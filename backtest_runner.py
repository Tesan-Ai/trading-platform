import pandas as pd

from replay_engine import run_replay


def print_results(portfolio) -> None:
    trades = pd.DataFrame(portfolio.trade_log)
    equity_curve = pd.DataFrame(portfolio.equity_curve)

    if equity_curve.empty:
        print("No replay results.")
        return

    starting_equity = float(equity_curve.iloc[0]["equity"])
    ending_equity = float(equity_curve.iloc[-1]["equity"])
    total_return = ((ending_equity - starting_equity) / starting_equity) * 100.0

    print("\nReplay complete")
    print(f"Starting equity: ${starting_equity:,.2f}")
    print(f"Ending equity:   ${ending_equity:,.2f}")
    print(f"Total return:    {total_return:.2f}%")

    if not trades.empty:
        sells = trades[trades["action"] == "SELL"].copy()

        if not sells.empty and "pnl_percent" in sells.columns:
            wins = sells[sells["pnl_percent"] > 0]
            losses = sells[sells["pnl_percent"] <= 0]

            win_rate = (len(wins) / len(sells)) * 100.0
            average_win = wins["pnl_percent"].mean() * 100.0 if not wins.empty else 0.0
            average_loss = losses["pnl_percent"].mean() * 100.0 if not losses.empty else 0.0

            print(f"Closed trades:   {len(sells)}")
            print(f"Win rate:        {win_rate:.2f}%")
            print(f"Average win:     {average_win:.2f}%")
            print(f"Average loss:    {average_loss:.2f}%")

        print("\nLast 10 trades:")
        print(trades.tail(10).to_string(index=False))
    else:
        print("No trades were executed.")


if __name__ == "__main__":
    symbols = [
        "AAPL", "MSFT", "NVDA", "AMD", "META",
        "TSLA", "AMZN", "PLTR", "SOFI", "RKLB"
    ]

    portfolio = run_replay(
        symbols=symbols,
        data_dir="historical_data",
        starting_cash=100000.0
    )

    print_results(portfolio)
