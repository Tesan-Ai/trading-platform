# Trading Platform Architecture

## Goal

Build a trading platform that improves strategies through evidence, not guesses. The system should move ideas through clear stages:

1. Research-only backtests
2. Walk-forward validation
3. Paper trading
4. Broker reconciliation
5. Carefully gated live execution

Live trading stays disabled until a strategy passes validation and paper gates.

## Current Platform Layers

- **Broker:** Alpaca paper trading first; future brokers plug into `brokers/`.
- **Database:** Supabase Postgres for durable positions, signals, experiments, and risk events.
- **Backend/runtime:** Python in Docker, scheduled by Render worker/cron jobs.
- **Dashboard:** Streamlit now; Next.js later if the product needs a production UI.
- **Monitoring:** Sentry, Slack/Discord alerts, and daily email reports.
- **Research:** Current replay engine plus Backtesting.py experiments; VectorBT or Polygon.io can be added later.
- **DevOps:** GitHub, GitHub Actions, pytest, and `.env` secrets.

- `features/`: timestamp-safe indicators and session features
- `strategies/`: entry/exit logic with no broker side effects
- `regime/`: market condition filters
- `risk/`: kill switches, loss limits, position limits, and trade limits
- `backtesting/`: replay engine for strategy validation
- `analytics/`: trade metrics, setup journal, and reports
- `validation/`: platform gate decisions for research, paper, and live readiness
- `experiments/`: saved run records and summary history

## New Improvement Loop

1. Run walk-forward validation:

```bash
.venv/bin/python walk_forward_runner.py \
  --strategy opening_range_vwap_momentum_v1 \
  --start-date 2025-09-03 \
  --end-date 2026-06-03 \
  --orvwap-quality-profile
```

2. Review the saved experiment under `research_results/experiments/`.
3. Reject configs that fail the validation gate.
4. Use fold-level failures to decide the next strategy change.
5. Only promote a strategy to paper trading after the backtest gate passes.

## Promotion Gates

Backtest candidates must clear minimum closed trades, positive expectancy, profit factor, drawdown, and win-rate checks.

Paper-to-live candidates use stricter thresholds from `config.py`:

- `MIN_PAPER_TRADES_BEFORE_LIVE`
- `MIN_PROFIT_FACTOR_BEFORE_LIVE`
- `MIN_EXPECTANCY_BEFORE_LIVE`
- `MAX_VALIDATED_DRAWDOWN`

## Next Architecture Upgrades

- Alpaca paper broker adapter: `brokers/alpaca_paper.py`.
- Supabase schema: create tables for experiments, signals, positions, orders, fills, risk events, and daily reports.
- Account reconciliation: `reconcile_runner.py` compares local positions with broker/account state.
- Strategy scorecards: per-symbol, per-day, per-regime, per-exit reason promotion checks.
- Data health checks: missing bars, stale data, abnormal spreads, and split-adjustment warnings.
- Paper journal ingestion: combine real paper fills with the same validation gates.

## Target Platform Stack

| Layer | Platform |
| --- | --- |
| Broker | Alpaca paper trading |
| Database | Supabase Postgres |
| Backend/runtime | Python, Docker, Render worker or cron job |
| Dashboard | Streamlit now, Next.js later |
| Monitoring | Sentry, Slack or Discord alerts, daily email report |
| Research | Current replay engine, Backtesting.py, Alpaca historical data, optional Polygon.io |
| DevOps | GitHub, GitHub Actions, pytest, `.env` secrets |

## Supabase Tables

The starter schema lives at `database/schema.sql`:

- `experiments`: every backtest or paper validation run
- `signals`: accepted and rejected strategy signals
- `orders`: broker order requests and responses
- `fills`: broker fill events
- `positions`: reconciled broker positions
- `risk_events`: kill switches, blocked trades, stale data, reconciliation failures
- `daily_reports`: daily summary payloads for dashboard and email
