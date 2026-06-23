# ETF 9-Month Research Summary

Run completed: `2026-06-04 05:41 ET`

Data window:

- Start: `2025-09-03`
- End: `2026-06-03`
- Capital: `$25,000`
- Universe: `SPY, QQQ, XLC, XLY, XLP, XLE, XLF, XLV, XLI, XLB, XLRE, XLK, XLU, MTUM, QUAL, VLUE, USMV, SIZE`

Output files:

- `raw_backtests_20260604_054136.csv`
- `best_configs_20260604_054136.csv`

## Result

The current ETF momentum-breakout strategy did **not** produce a profitable configuration in this 128-config sweep.

Key counts:

- Configs tested: `128`
- Positive expectancy configs: `0`
- Profit factor > 1 configs: `0`

Best expectancy config:

- Run ID: `10`
- Buy window: `09:45-13:30`
- RSI band: `40-70`
- RVOL min: `0.8`
- Require breakout: `True`
- Max hold minutes: `60`
- Max positions: `2`
- Closed trades: `49`
- Win rate: `18.37%`
- Profit factor: `0.083`
- Expectancy: `-$0.82/trade`
- Best ticker: `XLE`
- Worst ticker: `XLF`

## Interpretation

The current base strategy is not viable on the 9-month ETF universe. The losses are not a small tuning issue: win rates are low, profit factors are far below 1.0, and every tested config has negative expectancy.

Do not move this strategy to paper/live execution as-is.

## Next Research Direction

The ETF universe is useful, but this strategy form is wrong for it. Next steps should test:

- mean-reversion ETF strategy instead of breakout-only momentum
- relative-strength rotation between sectors
- market regime-specific ETF allocation
- long/flat trend following on SPY/QQQ with daily or 15-minute bars
- avoid XLF-like weak performers or separately model sector behavior
