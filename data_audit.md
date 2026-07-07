# Data Audit — IEX vs SIP Feed (2026-07-07)

## Why this audit happened

An external review of this platform flagged that Alpaca's IEX feed represents
only a small slice of consolidated market volume, and that every relative-volume
(RVOL) filter, volume-ratio gate, and ML Brain volume feature in this repo was
built on that feed. This document records the verification and the fix.

## Verification method

1. **Live check** (`scripts/data_audit.py`): pulled the last 5 trading days for
   NVDA and AAPL on both `feed=iex` and `feed=sip` via the same Alpaca account,
   same API keys already configured in `.env`.
2. **Historical check**: re-downloaded the full existing history (2023-01-03 to
   2026-06-03) for NVDA, AAPL, SPY with `feed=sip` and compared regular-session
   (13:30-20:00 UTC) volume totals against the previously-committed IEX CSVs
   (backed up to `historical_data_iex_backup/` before overwriting).

## Results

### Last 5 trading days (live pull, 2026-07-07)

| Symbol | IEX bars | IEX volume | SIP bars | SIP volume | SIP / IEX |
| --- | --- | --- | --- | --- | --- |
| NVDA | 783 | 9,903,460 | 1,864 | 256,675,842 | **25.9x** |
| AAPL | 793 | 3,699,448 | 1,704 | 111,095,754 | **30.0x** |

### Full history, regular session only (2023-01-03 to 2026-06-03)

| Symbol | IEX volume (old) | SIP volume (new) | SIP / IEX |
| --- | --- | --- | --- |
| NVDA | 1,797,975,070 | 112,616,948,715 | **62.6x** |
| AAPL | 236,381,762 | 6,872,339,569 | **29.1x** |
| SPY | 878,072,373 | 47,968,206,314 | **54.6x** |

The account has SIP entitlement — no subscription error, no paid plan needed.
Alpaca's free historical SIP access works as long as the query end time is at
least 15 minutes in the past (satisfied by any backtest/training run, since
those never query "live now").

## Conclusion

**Confirmed and severe.** Every backtest, walk-forward run, and ML Brain
training run performed before 2026-07-07 used volume figures that were roughly
25x-63x too low. Any RVOL-based filter decision, volume-ratio gate pass/fail,
or ML feature derived from volume in those runs should be treated as invalid.

## Action taken

1. Backed up old IEX-feed CSVs to `historical_data_iex_backup/` (NVDA, TSLA,
   AMD, META, AAPL, MSFT, AMZN, SPY, QQQ).
2. Re-downloaded the same 9 symbols with `feed=sip`, 2023-01-03 to 2026-06-03,
   into `historical_data/` (overwriting the IEX versions).
3. Changed `config.ALPACA_DATA_FEED` default from `"iex"` to `"sip"`.
4. Changed `download_historical_data.py --feed` default from `"iex"` to `"sip"`.

## What is now invalidated and must be re-run

- The Opening Range VWAP Momentum backtest results shown in the dashboard
  (`research_results/research_lab/`) — re-run via `research_lab_runner.py`.
- The ORB-PBC baseline report
  (`research_results/orb_pbc_v1/20260701_214334_orb_pbc_v1_202dcfdd.md`) — the
  30-trade, 76.7% win rate result was computed on IEX volume. Re-run via
  `orb_pbc_runner.py`.
- The ML Trade Brain v1 model and all evaluation JSONs in
  `research_results/ml_brain/` — every volume-derived feature (`relative_volume`,
  `volume_spike`) was built on the old feed. Re-train via `ml_brain_runner.py train`.
- The ETF momentum sweep (`research_results_etf_9mo/`) — directionally likely
  still not viable (ETF volume ratios shift less than single names), but not
  re-verified.

## Not yet done (still open)

- AAPL, MSFT, AMZN, and all ETF/factor symbols were re-pulled to match the
  2023-2026 window only for the 9 core symbols above. `historical_data_iex_backup/`
  still holds the old files if a rollback is ever needed — do not delete it
  until the re-run backtests are validated.
- Bid/ask spread data is still unavailable in any feed pulled here (Alpaca's
  `StockBarsRequest` returns OHLCV only, no spread) — the `spread_pct` filter
  remains unenforced in backtests.
- No FOMC/CPI/earnings calendar exists yet (tracked separately as PR-2).
- New SIP files include pre-market/after-hours bars (00:00-23:59 timestamps)
  that the old IEX files may not have had as densely. Session-feature builders
  in `features/session_features.py` already filter to the regular session, but
  confirm this before running walk-forward.
