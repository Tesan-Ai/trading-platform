import argparse
from datetime import datetime, time as dt_time, timedelta
from zoneinfo import ZoneInfo

from trader import run_trading_day
from portfolio_manager import load_open_positions, close_position
from performance import print_performance_summary
from equity_tracker import record_equity, calculate_equity
from ai_model import score_stock
from logger import log_trade

EASTERN = ZoneInfo("America/New_York")

MARKET_START = dt_time(9, 30)
MARKET_END = dt_time(16, 0)
FORCE_CLOSE_TIME = dt_time(15, 55)


def is_weekday(current_time):
    return current_time.weekday() < 5


def print_open_positions(current_time):
    open_positions = load_open_positions()

    print("\nCurrent open positions:")
    if not open_positions:
        print("No open positions")
        return

    for position in open_positions:
        symbol = position["symbol"]
        shares = int(position["shares"])
        entry_price = float(position["entry_price"])

        line = (
            f'{symbol} | '
            f'Shares={shares} | '
            f'Entry Price={entry_price:.2f}'
        )

        stock_result = score_stock(symbol, current_time=current_time)

        if stock_result is not None:
            current_price = float(stock_result["close"])
            pnl = (current_price - entry_price) * shares
            line += (
                f' | Current Price={current_price:.2f}'
                f' | Unrealized P/L={pnl:.2f}'
            )

        print(line)


def calculate_daily_pnl(start_equity):
    current_equity = calculate_equity()
    return current_equity - start_equity


def force_close_all_positions(current_time):
    print("\nForce closing all positions before market close...\n")

    open_positions = load_open_positions()

    for position in open_positions:
        symbol = position["symbol"]
        shares = int(position["shares"])
        entry_price = float(position["entry_price"])

        stock_result = score_stock(symbol, current_time=current_time)

        if stock_result is None:
            continue

        current_price = float(stock_result["close"])
        pnl = (current_price - entry_price) * shares

        close_position(symbol)

        log_trade(
            action="SELL",
            symbol=symbol,
            price=current_price,
            shares=shares,
            position_value=round(current_price * shares, 2),
            score=stock_result["score"],
            pnl=round(pnl, 2),
            reason="end of day close"
        )

        print(
            f'EOD SELL {symbol} | '
            f'Shares={shares} | '
            f'Price={current_price:.2f} | '
            f'P/L={pnl:.2f}'
        )


def build_market_minutes_for_day(replay_date):
    start_datetime = datetime.combine(replay_date, MARKET_START, tzinfo=EASTERN)
    end_datetime = datetime.combine(replay_date, MARKET_END, tzinfo=EASTERN)

    current_time = start_datetime
    minutes = []

    while current_time <= end_datetime:
        minutes.append(current_time)
        current_time += timedelta(minutes=1)

    return minutes


def run_replay_for_day(replay_date):
    market_minutes = build_market_minutes_for_day(replay_date)

    if not market_minutes:
        print("No market minutes generated.")
        return

    first_time = market_minutes[0]

    if not is_weekday(first_time):
        print(f"{replay_date} is not a weekday.")
        return

    print(f"Starting replay for {replay_date.strftime('%Y-%m-%d')}")
    print(f"Replay window: {MARKET_START.strftime('%H:%M')} to {MARKET_END.strftime('%H:%M')} ET")
    print()

    start_of_day_equity = calculate_equity()
    print(f"Start of day equity: {start_of_day_equity:.2f}")

    for current_time in market_minutes:
        if current_time.time() >= FORCE_CLOSE_TIME:
            force_close_all_positions(current_time)
            record_equity()
            continue

        current_pnl = calculate_daily_pnl(start_of_day_equity)

        print(f"\n[{current_time.strftime('%Y-%m-%d %I:%M:%S %p ET')}] Running replay cycle...")
        print(f"Daily PnL: {current_pnl:.2f}")

        try:
            sold_trades, bought_trades = run_trading_day(
                current_time=current_time,
                current_pnl=current_pnl
            )

            print("Total sells this cycle:", len(sold_trades))
            print("Total buys this cycle:", len(bought_trades))

            print_open_positions(current_time)
            print_performance_summary()
            record_equity()

        except Exception as error:
            print("Error during replay cycle:", str(error))

    ending_equity = calculate_equity()

    print()
    print("Replay complete")
    print(f"Starting equity: {start_of_day_equity:.2f}")
    print(f"Ending equity:   {ending_equity:.2f}")
    print(f"Net PnL:         {ending_equity - start_of_day_equity:.2f}")


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True, help="Replay date in YYYY-MM-DD format")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    replay_date = datetime.strptime(args.date, "%Y-%m-%d").date()
    run_replay_for_day(replay_date)
