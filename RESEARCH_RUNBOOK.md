# Overnight Research Runbook

Use this when you want Codex to run a long profitability search overnight.

## Dry Run

Run a tiny sweep against already downloaded local data:

```bash
.venv/bin/python overnight_research_runner.py \
  --start-date 2026-03-10 \
  --end-date 2026-03-13 \
  --core-symbols \
  --max-configs 2
```

## Download Data First

Example for a larger run:

```bash
.venv/bin/python download_historical_data.py \
  --start-date 2026-03-01 \
  --end-date 2026-06-03 \
  --universe etf \
  --output-dir historical_data
```

## Overnight Sweep

```bash
.venv/bin/python overnight_research_runner.py \
  --start-date 2026-03-01 \
  --end-date 2026-06-03 \
  --etf-universe \
  --capital 25000 \
  --output-dir research_results
```

Outputs:

- `research_results/raw_backtests_*.csv`
- `research_results/best_configs_*.csv`
- `research_results/trade_setup_journal_*.csv`
- `research_results/setup_summary_*.csv`

## Notes

- Keep the Mac awake overnight.
- The runner does not enable live trading.
- The ranked results are research candidates, not approval to trade live.
- Prefer configs with enough trades, positive expectancy, profit factor above 1.25, and controlled drawdown.
- Use the setup journal to inspect each closed trade's entry, stop, target, risk/reward, regime, exit reason, and setup-quality label.
- Use the setup summary to reject weak setup types quickly instead of repeatedly sweeping tiny parameter changes.
