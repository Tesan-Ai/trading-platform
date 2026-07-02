# ML Trade Brain v1

**Filter/scorer only.** ML Trade Brain never places orders. Flow:

```
strategy candidate → ML brain score → risk checks → Alpaca PAPER execution
```

## Config (`.env`)

```env
ML_BRAIN_ENABLED=false
ML_MODEL_PATH=models/ml_trade_brain_v1/model.joblib
ML_THRESHOLD_DEFAULT=0.60
ML_MIN_TRADE_COUNT_FOR_MODEL=50
ML_FAIL_CLOSED=true
```

- `ML_FAIL_CLOSED=true` — missing model or prediction error → **REJECT**
- `ML_BRAIN_ENABLED=false` — pass-through (all strategy-approved candidates allowed)

## Train

```bash
.venv/bin/python ml_brain_runner.py train \
  --start-date 2025-09-03 \
  --end-date 2026-06-03 \
  --symbols NVDA META AMD TSLA AAPL MSFT AMZN \
  --model-type logistic
```

Collects labeled candidates from historical backtest (target-before-stop labels), trains LogisticRegression or RandomForest with **time-based split** (no random shuffle).

Artifacts:
- `models/ml_trade_brain_v1/model.joblib`
- `models/ml_trade_brain_v1/metadata.json`
- `logs/ml_labeled_candidates.csv`
- `research_results/ml_brain/evaluation_*.json`

## Evaluate

```bash
.venv/bin/python ml_brain_runner.py evaluate \
  --start-date 2025-09-03 \
  --end-date 2026-06-03
```

## Backtest with ML off vs on

```bash
# ML off (default)
ML_BRAIN_ENABLED=false .venv/bin/python research_lab_runner.py \
  --strategy opening_range_vwap_momentum_v1 \
  --start-date 2025-09-03 --end-date 2026-06-03

# ML on (requires trained model)
ML_BRAIN_ENABLED=true .venv/bin/python research_lab_runner.py \
  --strategy opening_range_vwap_momentum_v1 \
  --start-date 2025-09-03 --end-date 2026-06-03
```

## Dashboard

```bash
streamlit run streamlit_app.py
```

Tabs: Overview, Backtest Results, ML Brain, Trades, Risk & Safety, Advanced JSON.

## Supabase

Run `database/schema_ml_brain.sql` after `database/schema.sql` to create ML tables.

## Feature gaps (placeholders)

These fields use safe defaults until wired to live data:
- `return_1m`, `return_5m`, `return_15m` — populated when minute frame passed to feature builder
- `spread_pct` — often missing in historical CSVs (logged as missing)

## Safety

- Live trading flags unchanged
- ML cannot bypass `RiskGate.can_trade()`
- Failed predictions reject when `ML_FAIL_CLOSED=true`
