import config
from bot_runner import run_trading_cycle
from portfolio_manager import load_open_positions


print("E*TRADE bot")
print(f"Strategy: {config.ACTIVE_STRATEGY}")
if config.ACTIVE_STRATEGY in {config.ORVWAP_STRATEGY_NAME, "daily_trend_v1"}:
    symbols = list(getattr(config, "TRADE_SYMBOLS", []) or config.ORVWAP_UNIVERSE)
    print(f"Symbols: {', '.join(symbols)}")
else:
    print(f"Scan mode: {getattr(config, 'SCAN_MODE', 'market')} (full US equity universe)")
print(f"Trading mode: {config.TRADING_MODE}")
if config.TRADING_MODE == "LIVE":
    print(f"Live enabled: {config.ENABLE_LIVE_TRADING or config.LIVE_ENABLED}")
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
