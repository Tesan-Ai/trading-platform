from __future__ import annotations

import pandas as pd


def analyze_drawdowns(equity_curve: list[dict], trade_rows: list[dict] | None = None) -> dict:
    if not equity_curve:
        return {
            "max_drawdown": 0.0,
            "average_drawdown": 0.0,
            "max_drawdown_duration": 0,
            "average_recovery_time": None,
            "worst_recovery_time": None,
            "current_drawdown": 0.0,
            "peak_timestamp": None,
            "trough_timestamp": None,
            "suggestions": ["No equity curve was available, so drawdown suggestions are not available."],
            "series": [],
        }

    data = pd.DataFrame(equity_curve).copy()
    data["timestamp"] = pd.to_datetime(data["timestamp"], utc=True, errors="coerce")
    data["equity"] = pd.to_numeric(data["equity"], errors="coerce")
    data = data.dropna(subset=["equity"]).reset_index(drop=True)
    if data.empty:
        return analyze_drawdowns([], trade_rows)

    data["peak"] = data["equity"].cummax()
    data["drawdown"] = ((data["peak"] - data["equity"]) / data["peak"]).fillna(0.0)
    trough_index = int(data["drawdown"].idxmax())
    peak_value = data.loc[:trough_index, "equity"].max()
    peak_index = int(data.loc[:trough_index, "equity"].idxmax())
    durations, recoveries = _drawdown_periods(data)

    return {
        "max_drawdown": float(data["drawdown"].max()),
        "average_drawdown": float(data.loc[data["drawdown"] > 0, "drawdown"].mean() or 0.0),
        "max_drawdown_duration": max(durations) if durations else 0,
        "average_recovery_time": float(sum(recoveries) / len(recoveries)) if recoveries else None,
        "worst_recovery_time": max(recoveries) if recoveries else None,
        "current_drawdown": float(data.iloc[-1]["drawdown"]),
        "peak_timestamp": _iso(data.iloc[peak_index]["timestamp"]),
        "trough_timestamp": _iso(data.iloc[trough_index]["timestamp"]),
        "peak_equity": float(peak_value),
        "trough_equity": float(data.iloc[trough_index]["equity"]),
        "suggestions": drawdown_suggestions(trade_rows or []),
        "series": [
            {
                "timestamp": _iso(row["timestamp"]),
                "equity": float(row["equity"]),
                "drawdown": float(row["drawdown"]),
            }
            for _, row in data.iterrows()
        ],
    }


def drawdown_suggestions(trade_rows: list[dict]) -> list[str]:
    if not trade_rows:
        return ["No closed trades were available, so drawdown reduction suggestions are limited."]

    data = pd.DataFrame(trade_rows).copy()
    data["pnl_dollars"] = pd.to_numeric(data.get("pnl_dollars"), errors="coerce").fillna(0.0)
    data["entry_timestamp"] = pd.to_datetime(data.get("entry_timestamp"), errors="coerce")
    losses = data[data["pnl_dollars"] < 0].copy()
    suggestions = []

    if "ticker" in data and not losses.empty:
        by_symbol = data.groupby("ticker", dropna=False)["pnl_dollars"].agg(["sum", "count", "mean"])
        bad_symbols = by_symbol[(by_symbol["sum"] < 0) & (by_symbol["count"] >= 2)].sort_values("sum")
        if not bad_symbols.empty:
            symbol = str(bad_symbols.index[0])
            suggestions.append(
                f"Review or exclude {symbol}: it has negative total PnL and at least two closed trades in this sample."
            )

    if not losses.empty and data["entry_timestamp"].notna().any():
        data["entry_hour"] = data["entry_timestamp"].dt.hour
        hourly = data.groupby("entry_hour")["pnl_dollars"].agg(["sum", "count"])
        bad_hour = hourly[(hourly["sum"] < 0) & (hourly["count"] >= 2)].sort_values("sum")
        if not bad_hour.empty:
            hour = int(bad_hour.index[0])
            suggestions.append(
                f"Test blocking entries during hour {hour}:00 ET because losses cluster there in this backtest."
            )

    if data["entry_timestamp"].notna().any():
        day_counts = data.groupby(data["entry_timestamp"].dt.date)["pnl_dollars"].agg(["count", "sum"])
        heavy_loss_days = day_counts[(day_counts["count"] >= 3) & (day_counts["sum"] < 0)]
        if not heavy_loss_days.empty:
            suggestions.append(
                "Test reducing max trades per day because some high-trade days finished negative."
            )

    if "spy_trend" in data:
        by_regime = data.groupby("spy_trend", dropna=False)["pnl_dollars"].agg(["sum", "count"])
        bad_regime = by_regime[(by_regime["sum"] < 0) & (by_regime["count"] >= 2)].sort_values("sum")
        if not bad_regime.empty:
            suggestions.append(
                f"Tighten market filters around {bad_regime.index[0]} because that regime shows negative expectancy."
            )

    while len(suggestions) < 3:
        suggestions.append(
            "Keep this parameter unchanged until a larger out-of-sample sample identifies a repeatable drawdown cluster."
        )
    return suggestions[:3]


def _drawdown_periods(data: pd.DataFrame) -> tuple[list[int], list[int]]:
    durations = []
    recoveries = []
    current_start = None

    for index, row in data.iterrows():
        in_drawdown = float(row["drawdown"]) > 0
        if in_drawdown and current_start is None:
            current_start = index
        if not in_drawdown and current_start is not None:
            duration = index - current_start
            durations.append(duration)
            recoveries.append(duration)
            current_start = None

    if current_start is not None:
        durations.append(len(data) - current_start)

    return durations, recoveries


def _iso(value) -> str | None:
    if pd.isna(value):
        return None
    return value.isoformat()
