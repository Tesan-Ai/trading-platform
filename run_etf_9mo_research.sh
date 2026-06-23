#!/usr/bin/env bash
set -euo pipefail

mkdir -p logs research_results_etf_9mo

LOG_FILE="logs/etf_9mo_research_$(date +%Y%m%d_%H%M%S).log"
PID_FILE="logs/etf_9mo_research.pid"

nohup .venv/bin/python -u overnight_research_runner.py \
  --start-date 2025-09-03 \
  --end-date 2026-06-03 \
  --download \
  --etf-universe \
  --capital 25000 \
  --max-configs 500 \
  --output-dir research_results_etf_9mo \
  > "$LOG_FILE" 2>&1 &

echo "$!" > "$PID_FILE"
echo "Started ETF 9-month research run"
echo "PID: $(cat "$PID_FILE")"
echo "Log: $LOG_FILE"
echo "Results directory: research_results_etf_9mo"
