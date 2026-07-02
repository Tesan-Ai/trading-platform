from collections import Counter, defaultdict
import math

import pandas as pd

from analytics.strategy_diagnostics import build_strategy_diagnostics
from analytics.trade_analytics import calculate_report, print_report


def build_orvwap_report(
    trade_rows: list[dict],
    equity_curve: list[dict],
    signal_rows: list[dict] | None = None,
    rejection_counts: dict[str, int] | None = None,
) -> dict:
    base_report = calculate_report(trade_rows, equity_curve)
    report = dict(base_report)
    report["trades"] = trade_rows
    report["equity_curve"] = equity_curve
    if equity_curve:
        starting_equity = float(equity_curve[0]["equity"])
        ending_equity = float(equity_curve[-1]["equity"])
        report["starting_equity"] = starting_equity
        report["ending_equity"] = ending_equity
        report["total_return"] = (ending_equity - starting_equity) / starting_equity if starting_equity else 0.0

    if trade_rows:
        data = pd.DataFrame(trade_rows)
        report["total_pnl"] = float(data["pnl_dollars"].sum())
        report["performance_by_day_of_week"] = (
            data.assign(day_of_week=data["entry_timestamp"].dt.day_name())
            .groupby("day_of_week")["pnl_dollars"]
            .sum()
            .to_dict()
        )
        report["performance_by_spy_vwap"] = _performance_by_flag(data, "spy_above_vwap_at_entry")
        report["performance_by_qqq_vwap"] = _performance_by_flag(data, "qqq_above_vwap_at_entry")
    else:
        report["total_pnl"] = 0.0
        report["performance_by_day_of_week"] = {}
        report["performance_by_spy_vwap"] = {}
        report["performance_by_qqq_vwap"] = {}

    report["skipped_signals_by_reason"] = rejection_counts or _rejection_counts(signal_rows)
    report["accepted_signals"] = _count_event(signal_rows, "ENTRY")
    report["rejected_signals"] = sum(report["skipped_signals_by_reason"].values())
    report["diagnostics"] = build_strategy_diagnostics(trade_rows, equity_curve, signal_rows)
    return report


def print_orvwap_report(report: dict) -> None:
    print_report(report)
    print("\nORVWAP EXTENDED REPORT")
    print("----------------------")
    print(f'Total P/L:           ${report.get("total_pnl", 0.0):,.2f}')
    print(f'Accepted signals:    {report.get("accepted_signals", 0)}')
    print(f'Rejected signals:    {report.get("rejected_signals", 0)}')

    if report.get("performance_by_day_of_week"):
        print("\nPerformance by day of week:")
        for day, pnl in report["performance_by_day_of_week"].items():
            print(f"  {day}: ${pnl:,.2f}")

    if report.get("performance_by_spy_vwap"):
        print("\nPerformance when SPY above/below VWAP:")
        for label, pnl in report["performance_by_spy_vwap"].items():
            print(f"  {label}: ${pnl:,.2f}")

    if report.get("skipped_signals_by_reason"):
        print("\nSkipped signals by rejection reason:")
        for reason, count in sorted(
            report["skipped_signals_by_reason"].items(),
            key=lambda item: item[1],
            reverse=True,
        ):
            print(f"  {reason}: {count}")

    candidates = report.get("diagnostics", {}).get("improvement_candidates", [])
    if candidates:
        print("\nStrategy improvement candidates:")
        for candidate in candidates[:5]:
            print(f"  [{candidate['severity']}] {candidate['finding']} {candidate['recommendation']}")


def save_orvwap_report(report: dict, output_dir: str) -> str:
    import json
    import os

    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, "orvwap_report.json")
    with open(output_path, "w", encoding="utf-8") as file:
        json.dump(_json_safe(report), file, indent=2, default=str)
    return output_path


def _json_safe(value):
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value


def _performance_by_flag(data: pd.DataFrame, column: str) -> dict:
    if column not in data.columns:
        return {}
    grouped = data.groupby(column, dropna=False)["pnl_dollars"].sum()
    return {str(key): float(value) for key, value in grouped.items()}


def _rejection_counts(signal_rows: list[dict] | None) -> dict[str, int]:
    if not signal_rows:
        return {}

    counts: Counter[str] = Counter()
    for row in signal_rows:
        if row.get("entry_approved"):
            continue
        counts[row.get("rejection_reason") or "unknown"] += 1
    return dict(counts)


def _count_event(signal_rows: list[dict] | None, event_type: str) -> int:
    if not signal_rows:
        return 0
    return sum(1 for row in signal_rows if row.get("event_type") == event_type)
