# Trading Platform

Paper-only trading platform with single-strategy execution and research-only multi-strategy comparison.

## Safety Defaults

- Active strategy: `opening_range_vwap_momentum_v1`
- Trading mode: `PAPER`
- Live trading is disabled and blocked by the paper execution layer.
- The old ETF momentum-breakout strategy is kept for research only and is not the default active strategy.
- OpenAI/AI code is placeholder-only and cannot place trades or change risk rules.

## Strategy

The default active execution strategy is `opening_range_vwap_momentum_v1`. It trades early opening-range VWAP momentum in:

`NVDA`, `TSLA`, `AMD`, `AAPL`, `META`, `MSFT`, `AMZN`

Market filters:

- `SPY` must be risk-on/above VWAP.
- Tech symbols require `QQQ` above VWAP.
- Market-filter blocks are logged with explicit reasons.

Entry window:

`09:35` to `10:30` Eastern.

Risk:

- Risk per trade: `0.375%` of equity.
- Max open positions: `1`.
- Max trades per day: `3`.
- Max losing trades per day: `2`.
- Max spread: `0.15%`.
- Max extension from VWAP: `1.5 ATR`.
- Force close time: `15:55` Eastern.
- No overnight holds.

## Architecture

- `strategies/opening_range_vwap_momentum.py`: strategy decision layer.
- `features/session_features.py`: market-data feature calculations.
- `market/filters.py`: SPY/QQQ market filter layer.
- `risk/orvwap_risk_engine.py`: ORVWAP risk approval and position sizing.
- `execution/paper.py`: paper-only execution layer.
- `database/observability.py`: local durable observability store.
- `supabase/migrations/001_observability_schema.sql`: Supabase/Postgres schema.
- `dashboard/api_server.py`: read-only local dashboard/API.
- `ai/explanations.py`: future AI explanation placeholders.

## Environment

Copy `.env.example` and fill in paper market-data keys:

```bash
cp .env.example .env
```

Required safety settings:

```bash
ACTIVE_STRATEGY=opening_range_vwap_momentum_v1
AUTO_STRATEGY_SELECTION=true
AUTO_STRATEGY_USE_SHADOW_LEADER=false
TRADING_MODE=PAPER
ENABLE_LIVE_TRADING=false
LIVE_ENABLED=false
```

## Run One Paper Cycle

```bash
python3 main.py
```

Each run writes terminal output, existing CSV logs, and database rows in:

```bash
data/trading_bot.sqlite3
```

Logged entities include:

- bot runs
- heartbeats
- buy/skip/hold signals
- trades
- positions
- risk events
- bot logs
- bot settings

## Run Dashboard/API

```bash
python3 -m dashboard.api_server
```

Open:

```txt
http://127.0.0.1:8080
```

Read-only API endpoints:

- `GET /api/status`
- `GET /api/signals`
- `GET /api/trades`
- `GET /api/positions`
- `GET /api/risk-events`
- `GET /api/logs`
- `GET /api/settings`

No live trading toggle exists.

## Multi-Strategy Research

Use the meta research runner to compare candidate strategies over the same window:

```bash
python3 multi_strategy_research_runner.py
```

Outputs:

```txt
research_results/multi_strategy/latest_multi_strategy_report.json
research_results/multi_strategy/multi_strategy_leaderboard.csv
```

This is research-only. It does not change `ACTIVE_STRATEGY`, route orders, or enable live trading.

Dashboard/API endpoints:

- `GET /api/multi-strategy-report`
- `GET /api/strategy-allocator`
- `GET /download/multi-strategy-report.json`
- `GET /download/multi-strategy-leaderboard.csv`

The allocator output answers: which strategy had the best historical evidence, which regimes looked favorable, and whether the result is still `SHADOW_ONLY` or can be considered a `PAPER_CANDIDATE`.

When `AUTO_STRATEGY_SELECTION=true`, each paper cycle reads the latest allocator report before trading. It only switches `ACTIVE_STRATEGY` automatically when the allocator mode is `PAPER_CANDIDATE`. `AUTO_STRATEGY_USE_SHADOW_LEADER=true` can force the current leaderboard leader in paper mode, but that is intentionally off by default because weak samples should be observed before they route orders.

## Supabase

The local SQLite store mirrors the Supabase schema. To create the cloud schema, run:

```sql
supabase/migrations/001_observability_schema.sql
```

The bot currently writes locally first. Supabase write integration is the next step once project credentials are available.

## Tests

Install dependencies:

```bash
python3 -m pip install -r requirements.txt
```

Run tests:

```bash
python3 -m pytest
```

## Before Live Trading

Live trading is intentionally not implemented. Before any live mode work:

- Paper trade enough samples to satisfy validation gates.
- Confirm positive expectancy and profit factor.
- Review all risk events and skipped-trade logs.
- Add walk-forward validation.
- Add dashboard controls only for safe paper settings.
- Keep AI explanations read-only.
