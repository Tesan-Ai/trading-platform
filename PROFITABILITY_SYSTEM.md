# Profitability-First Trading System

This project now has a stricter research path separate from the legacy replay.

## Principle

The bot should not trade real money unless the strategy passes walk-forward/backtest checks and paper trading gates.

Default behavior:

- `TRADING_MODE = PAPER_TRADING`
- `LIVE_ENABLED = false`
- `GLOBAL_KILL_SWITCH = false`
- no live gate passes unless performance thresholds are met

## New Components

- `features/feature_store.py`
  Centralized indicators: RSI, MACD slope, EMA 9/20/50/200, VWAP, ATR, RVOL, breakout distance, support distance, volume trend, bar range.

- `regime/market_regime.py`
  Classifies market proxy into `BULL_TREND`, `BEAR_TREND`, `CHOP`, `HIGH_VOLATILITY`, `LOW_LIQUIDITY`, or `RISK_OFF`.

- `strategies/momentum_breakout.py`
  Clean base strategy with no ML. Requires favorable regime, above VWAP, EMA alignment, RVOL, RSI band, breakout, controlled ATR, and 2:1 reward/risk.

- `risk/risk_gate.py`
  Global risk controls: kill switch, paper/live mode, PDT floor, daily loss, drawdown, max trades/day, max positions, losing-streak tracking.

- `analytics/trade_analytics.py`
  Builds closed-trade rows and reports win rate, profit factor, expectancy, average winner/loser, max drawdown, Sharpe estimate, best/worst ticker, time bucket, setup, losing streak, and indicator bucket edge.

- `backtesting/profitability_replay.py`
  Strict replay engine using timestamped feature calculation with no lookahead, slippage, realistic fills, regime gating, and strategy/risk gates.

- `dashboard_runner.py`
  Prints mode, live status, PDT cushion, risk limits, replay regime, performance report, and paper-to-live gate status.

## Current Local Results

Legacy tuned replay:

- Total return: `+0.10%`
- Closed trades: `3`
- Win rate: `66.67%`

Profitability-first replay:

- Total return: `0.00%`
- Closed trades: `0`
- Latest regime: `LOW_LIQUIDITY`

Interpretation: the stricter system is choosing not to trade the available local sample because regime/liquidity conditions are not favorable. This is safer than forcing trades just to make activity.

## Next Required Work

1. Download more historical data, including SPY or QQQ as the market-regime source.
2. Add walk-forward splits over multiple weeks/months.
3. Keep base strategy non-ML until analytics show positive expectancy.
4. Only after the base system proves edge, add an ML ranker for valid candidates.
5. Keep live trading disabled until paper gate passes.
