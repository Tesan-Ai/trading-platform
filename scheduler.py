import time
from datetime import datetime, time as dt_time
from zoneinfo import ZoneInfo

import config
from bot_runner import run_trading_cycle
from portfolio_manager import load_open_positions, close_position
from performance import print_performance_summary
from equity_tracker import record_equity, calculate_equity
from strategies.factory import get_strategy
from logger import log_trade

EASTERN = ZoneInfo("America/New_York")

MARKET_START = dt_time(9, 30)
MARKET_END = dt_time(16, 0)
FORCE_CLOSE_TIME = dt_time(15, 55)


def is_weekday(current_time):
    return current_time.weekday() < 5


def is_market_open_window(current_time):
    current_clock = current_time.time()
    return MARKET_START <= current_clock <= MARKET_END


def seconds_until_next_minute():
    now = datetime.now(EASTERN)
    return max(1, 60 - now.second)


def print_open_positions(current_time=None):
    open_positions = load_open_positions()

    print("\nCurrent open positions:")
    if not open_positions:
        print("No open positions")
        return

    for position in open_positions:
        print(
            f'{position["symbol"]} | '
            f'Shares={position["shares"]} | '
            f'Entry Price={position["entry_price"]:.2f}'
        )


def calculate_daily_pnl(start_equity):
    current_equity = calculate_equity()
    return current_equity - start_equity


def force_close_all_positions(current_time):
    strategy = get_strategy()
    if getattr(strategy, "holds_overnight", lambda: False)():
        return

    print("\nForce closing all positions before market close...\n")

    open_positions = load_open_positions()

    for position in open_positions:
        symbol = position["symbol"]
        shares = int(position["shares"])
        entry_price = float(position["entry_price"])

        close_position(symbol)
        log_trade(
            action="SELL",
            symbol=symbol,
            price=entry_price,
            shares=shares,
            position_value=round(entry_price * shares, 2),
            score=0.0,
            pnl=0.0,
            reason="end of day close"
        )

        print(f'EOD SELL {symbol} | Shares={shares} | Price={entry_price:.2f}')


def run_scheduler():
    print("Keys loaded successfully")
    print("Trading bot initialized successfully")
    print()

    start_of_day_equity = None

    while True:
        now = datetime.now(EASTERN)

        if is_weekday(now) and now.time() >= MARKET_START and start_of_day_equity is None:
            start_of_day_equity = calculate_equity()
            print(f"\nStart of day equity: {start_of_day_equity:.2f}")

        if is_weekday(now) and is_market_open_window(now):
            if now.time() >= FORCE_CLOSE_TIME:
                force_close_all_positions(now)
                time.sleep(60)
                continue

            current_pnl = 0.0
            if start_of_day_equity is not None:
                current_pnl = calculate_daily_pnl(start_of_day_equity)

            print(f"\n[{now.strftime('%Y-%m-%d %I:%M:%S %p ET')}] Running trading cycle...")
            print(f"Daily PnL: {current_pnl:.2f}")

            try:
                sold_trades, bought_trades = run_trading_cycle(
                    current_time=now,
                    current_pnl=current_pnl,
                )

                print("Total sells this cycle:", len(sold_trades))
                print("Total buys this cycle:", len(bought_trades))

                print_open_positions(current_time=now)
                print_performance_summary()
                record_equity()

            except Exception as error:
                print("Error during trading cycle:", str(error))

            sleep_seconds = seconds_until_next_minute()
            print(f"Sleeping {sleep_seconds} seconds until next cycle...")
            time.sleep(sleep_seconds)

        else:
            start_of_day_equity = None

            if not is_weekday(now):
                print(f"[{now.strftime('%Y-%m-%d %I:%M:%S %p ET')}] Weekend. Waiting...")
            else:
                print(f"[{now.strftime('%Y-%m-%d %I:%M:%S %p ET')}] Outside market hours. Waiting...")

            time.sleep(30)


if __name__ == "__main__":
    run_scheduler()
