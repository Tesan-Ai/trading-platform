import config
from bot_runner import run_trading_cycle
from portfolio_manager import load_open_positions


print("E*TRADE bot — paper trading mode")
print(f"Strategy: {config.ACTIVE_STRATEGY}")
if config.ACTIVE_STRATEGY == "daily_trend_v1":
    print(f"Symbols: {', '.join(config.TRADE_SYMBOLS)}")
else:
    print(f"Scan mode: {getattr(config, 'SCAN_MODE', 'market')} (full US equity universe)")
print(f"Trading mode: {config.TRADING_MODE}")
print()

sold_trades, bought_trades = run_trading_cycle()

print()
print("Total sells:", len(sold_trades))
print("Total buys:", len(bought_trades))
print()

open_positions = load_open_positions()
print("Current open positions:")
if not open_positions:
    print("No open positions")
else:
    for position in open_positions:
        print(
            f'{position["symbol"]} | '
            f'Shares={position["shares"]} | '
            f'Entry={position["entry_price"]} | '
            f'Opened={position["entry_timestamp"]}'
        )
