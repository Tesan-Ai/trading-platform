# Research Lab

The Research Lab turns prompt-style strategy questions into a repeatable workflow inside the repo. It does not place trades, does not enable live mode, and does not mutate production strategy settings.

## What It Does

`research_lab_runner.py` runs a strategy through the existing replay/backtest engine, then builds a structured report with:

- Backtest metrics
- Validation gate status
- Risk/reward analysis
- Drawdown analysis
- Monte Carlo bootstrap simulation
- Historical market-regime breakdown
- Conservative optimization suggestions
- Edge summary
- Capital allocation guidance
- Promotion recommendation

Reports are saved locally first. Supabase saving is optional and only runs when `SUPABASE_ENABLED=true`.

## How To Run

```bash
.venv/bin/python research_lab_runner.py \
  --strategy opening_range_vwap_momentum_v1 \
  --start-date 2025-09-03 \
  --end-date 2026-06-03 \
  --symbols NVDA TSLA AMD AAPL META MSFT AMZN \
  --market-filters SPY QQQ \
  --profile conservative \
  --monte-carlo-runs 1000
```

Outputs are written to:

```text
research_results/research_lab/
```

Each run creates:

- A JSON report
- A Markdown report
- `research_lab_summary.csv`

## Metric Meanings

- `closed_trades`: Number of completed trades.
- `win_rate`: Percent of trades with positive PnL.
- `profit_factor`: Gross profit divided by gross loss.
- `expectancy`: Average dollars made or lost per trade.
- `average_r_multiple`: Average PnL divided by initial dollars at risk.
- `max_drawdown`: Worst peak-to-trough equity decline.
- `Monte Carlo probability of loss`: Percent of bootstrap simulations that end below starting equity.
- `breakeven win rate`: Win rate required to break even given average win/loss size.

If a metric cannot be calculated from available data, the report uses `null` or `not available`.

## Status Interpretation

- `RESEARCH_ONLY`: The strategy is not ready for paper promotion.
- `PAPER_CANDIDATE`: The backtest gate passed, but paper validation is still required.
- `LIVE_CANDIDATE`: Reserved for a future paper-to-live gate. This does not enable live trading.

## Why Live Trading Is Still Disabled

Live trading remains disabled because research evidence is not the same as execution readiness. The platform requires:

1. Backtest validation
2. Walk-forward and out-of-sample review
3. Paper trading with broker reconciliation
4. Risk and monitoring checks
5. Explicit live-trading approval someday

The Research Lab only supports steps 1 and 2.

## Before Paper Trading

- Run the Research Lab over a meaningful historical window.
- Confirm the validation gate passes.
- Confirm Monte Carlo risk is acceptable.
- Review symbol, time-of-day, and regime breakdowns.
- Avoid changing multiple parameters at once.
- Re-run walk-forward validation after any suggested change.

## Before Live Trading Someday

- Keep `TRADING_MODE` out of `LIVE`.
- Complete paper trading with at least the configured minimum paper trades.
- Pass paper-to-live thresholds in `config.py`.
- Confirm broker reconciliation works.
- Confirm alerting and daily reporting work.
- Add explicit human approval before any live deployment.

## Dashboard

Run Streamlit to review the latest report:

```bash
.venv/bin/streamlit run streamlit_app.py
```

The dashboard shows the latest Research Lab report, charts, key metrics, recent experiments, symbol performance, regime performance, and warnings.
