# etrade-bot Project Audit

## What This Bot Does Today

This is a Python trading bot scaffold. Despite the project name, the current active market-data path uses Alpaca, not E*TRADE. E*TRADE keys are loaded, but there is no real E*TRADE order-placement integration in the current code.

The bot currently simulates positions and trades in CSV files:

- `portfolio/positions.csv` stores open and closed positions.
- `data/trades.csv` stores buy/sell logs.
- `data/equity_curve.csv` stores equity snapshots.

## Main Flow

1. `main.py` calls `run_trading_day`.
2. `trader.py` checks existing positions for sell signals.
3. `market_scanner.py` pulls tradable US equities from Alpaca, filters snapshots, then deep-scores top candidates.
4. `ai_model.py` calculates rule-based technical scores from intraday bars plus daily trend metrics.
5. `risk_manager.py` sizes positions using configured max trade size and portfolio exposure.
6. `portfolio_manager.py` records simulated buys/sells in local CSV files.

## Strategy Shape

The strategy is a rules-based momentum/pullback scorer, not a trained AI model yet.

It looks for:

- Active US equities.
- Price between `MIN_PRICE` and `MAX_PRICE`.
- Enough daily volume.
- Positive daily percent change.
- Acceptable bid/ask spread.
- Daily uptrend using 50-day and 200-day moving averages.
- Intraday pullback/continuation signals using returns, EMA ratio, VWAP distance, relative volume, and range position.

## Risk Controls

Current configured controls:

- Max positions: `MAX_POSITIONS`
- Max capital per trade: `MAX_CAPITAL_PER_TRADE`
- Max total exposure: `MAX_PORTFOLIO_EXPOSURE`
- Max daily loss: `MAX_DAILY_LOSS_PERCENT`
- Stop loss: `STOP_LOSS_PERCENT`
- Profit target: `PROFIT_TARGET_PERCENT`
- Forced end-of-day close in `scheduler.py`

## Important Gaps

- No real brokerage order placement is wired in.
- The bot logs simulated trades locally, so CSV state can drift from a real account.
- Alpaca credentials are required for scanner/model market data.
- The offline replay engine is stale: it uses short historical minute files while the scorer now requires long daily-trend context.
- There is almost no automated test coverage.
- Existing historical replay currently runs but produces zero trades.

## First Safe Roadmap

1. Keep everything in paper/simulation until backtests and paper logs show repeatable edge.
2. Fix replay/backtesting so the same scoring logic can be tested over realistic daily and intraday history.
3. Add broker/account reconciliation before any live trading.
4. Add order-placement behind an explicit paper/live mode flag.
5. Add hard kill switches: market-hours guard, max orders/day, max notional/day, and emergency liquidation/manual stop.
6. Add tests for scoring, position sizing, sell rules, cooldowns, and CSV state handling.
