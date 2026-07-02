"""CLI for ML Trade Brain v1 — train, evaluate, collect labeled data."""

from __future__ import annotations

import argparse
import json
from uuid import uuid4

import config
from ml_brain.registry import load_metadata, model_exists
from ml_brain.train_model import (
    collect_labeled_candidates,
    evaluate_model,
    labeled_rows_to_dataframe,
    save_evaluation_report,
    time_based_split,
    train_from_backtest,
)
from ml_brain.registry import load_model


def main() -> None:
    parser = argparse.ArgumentParser(description="ML Trade Brain v1 (filter/scorer only, PAPER-safe)")
    sub = parser.add_subparsers(dest="command", required=True)

    train_parser = sub.add_parser("train", help="Collect labels from backtest and train model")
    train_parser.add_argument("--start-date", required=True)
    train_parser.add_argument("--end-date", required=True)
    train_parser.add_argument("--symbols", nargs="+", default=list(config.ORVWAP_TRADE_SYMBOLS))
    train_parser.add_argument("--model-type", choices=["logistic", "random_forest"], default="logistic")
    train_parser.add_argument("--threshold", type=float, default=config.ML_THRESHOLD_DEFAULT)
    train_parser.add_argument("--data-dir", default="historical_data")

    eval_parser = sub.add_parser("evaluate", help="Evaluate the active saved model")
    eval_parser.add_argument("--start-date", required=True)
    eval_parser.add_argument("--end-date", required=True)
    eval_parser.add_argument("--symbols", nargs="+", default=list(config.ORVWAP_TRADE_SYMBOLS))
    eval_parser.add_argument("--threshold", type=float, default=config.ML_THRESHOLD_DEFAULT)
    eval_parser.add_argument("--data-dir", default="historical_data")

    collect_parser = sub.add_parser("collect", help="Collect labeled candidates only (no training)")
    collect_parser.add_argument("--start-date", required=True)
    collect_parser.add_argument("--end-date", required=True)
    collect_parser.add_argument("--symbols", nargs="+", default=list(config.ORVWAP_TRADE_SYMBOLS))
    collect_parser.add_argument("--data-dir", default="historical_data")
    collect_parser.add_argument("--output", default=config.ML_LABELED_DATA_PATH)

    args = parser.parse_args()

    if args.command == "train":
        report = train_from_backtest(
            symbols=[s.upper() for s in args.symbols],
            start_date=args.start_date,
            end_date=args.end_date,
            model_type=args.model_type,
            threshold=args.threshold,
            data_dir=args.data_dir,
        )
        report["run_id"] = f"ml_train_{uuid4().hex[:8]}"
        report["status"] = "completed"
        path = save_evaluation_report(report)
        print(json.dumps({"artifact": report.get("artifact_path"), "report": path, "test_metrics": report.get("test_metrics")}, indent=2))
        return

    if args.command == "collect":
        rows = collect_labeled_candidates(
            [s.upper() for s in args.symbols], args.start_date, args.end_date, args.data_dir
        )
        df = labeled_rows_to_dataframe(rows)
        df.to_csv(args.output, index=False)
        print(f"Saved {len(df)} labeled rows -> {args.output}")
        return

    if args.command == "evaluate":
        if not model_exists():
            raise SystemExit("No trained model found. Run: python ml_brain_runner.py train ...")
        rows = collect_labeled_candidates(
            [s.upper() for s in args.symbols], args.start_date, args.end_date, args.data_dir
        )
        df = labeled_rows_to_dataframe(rows)
        if df.empty:
            raise SystemExit("No labeled candidates in window.")
        pipeline = load_model()
        metadata = load_metadata()
        _, test_df = time_based_split(df)
        metrics = evaluate_model(pipeline, test_df, args.threshold)
        report = {"model_version": metadata.get("model_version"), "evaluation": metrics, "rows": len(df)}
        path = save_evaluation_report(report)
        print(json.dumps(report, indent=2, default=str))
        print(f"Report saved: {path}")


if __name__ == "__main__":
    main()
