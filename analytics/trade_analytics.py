import math
from collections import defaultdict
from zoneinfo import ZoneInfo

import pandas as pd

EASTERN = ZoneInfo("America/New_York")


def build_trade_rows(trade_log: list[dict]) -> list[dict]:
    open_trades = {}
    rows = []

    for trade in trade_log:
        if trade["action"] == "BUY":
            open_trades[trade["symbol"]] = trade
            continue

        if trade["action"] != "SELL" or trade["symbol"] not in open_trades:
            continue

        entry = open_trades.pop(trade["symbol"])
        entry_price = float(entry["price"])
        exit_price = float(trade["price"])
        shares = int(trade["shares"])
        pnl_dollars = (exit_price - entry_price) * shares
        pnl_percent = (exit_price - entry_price) / entry_price
        risk_per_share = entry.get("risk_per_share")
        risk_dollars = float(risk_per_share) * shares if risk_per_share is not None else None
        r_multiple = pnl_dollars / risk_dollars if risk_dollars and risk_dollars > 0 else None
        opening_range_high = entry.get("opening_range_high")
        opening_range_low = entry.get("opening_range_low")
        opening_range_size = (
            float(opening_range_high) - float(opening_range_low)
            if opening_range_high is not None and opening_range_low is not None
            else None
        )
        hold_minutes = (
            trade["timestamp"] - entry["timestamp"]
        ).total_seconds() / 60.0

        rows.append({
            "ticker": trade["symbol"],
            "entry_timestamp": entry["timestamp"],
            "exit_timestamp": trade["timestamp"],
            "entry_price": entry_price,
            "exit_price": exit_price,
            "position_size": shares,
            "stop_loss": entry.get("stop_loss"),
            "take_profit": entry.get("take_profit"),
            "risk_per_share": risk_per_share,
            "risk_dollars": risk_dollars,
            "r_multiple": r_multiple,
            "pnl_dollars": pnl_dollars,
            "pnl_percent": pnl_percent,
            "win_loss": "WIN" if pnl_dollars > 0 else "LOSS",
            "hold_time_minutes": hold_minutes,
            "strategy_name": entry.get("strategy_name"),
            "setup_type": entry.get("setup_type"),
            "rsi": entry.get("rsi_14"),
            "rvol": entry.get("relative_volume"),
            "atr": entry.get("atr_14"),
            "ema_trend": entry.get("ema_trend"),
            "vwap_position": entry.get("vwap_distance"),
            "distance_from_vwap_atr": entry.get("distance_from_vwap_atr"),
            "opening_range_high": opening_range_high,
            "opening_range_low": opening_range_low,
            "opening_range_midpoint": entry.get("opening_range_midpoint"),
            "opening_range_size": opening_range_size,
            "spy_trend": entry.get("market_regime"),
            "spy_above_vwap_at_entry": entry.get("spy_above_vwap_at_entry"),
            "qqq_above_vwap_at_entry": entry.get("qqq_above_vwap_at_entry"),
            "vix_regime": entry.get("vix_regime"),
            "sector": entry.get("sector", "UNKNOWN"),
            "spread": entry.get("spread_percent"),
            "volume": entry.get("volume"),
            "selected_stop_method": entry.get("selected_stop_method"),
            "entry_reason": entry.get("reason"),
            "exit_reason": trade.get("reason")
        })

    return rows


def calculate_report(trade_rows: list[dict], equity_curve: list[dict]) -> dict:
    if not trade_rows:
        return {
            "closed_trades": 0,
            "win_rate": 0.0,
            "profit_factor": 0.0,
            "expectancy": 0.0,
            "average_winner": 0.0,
            "average_loser": 0.0,
            "max_drawdown": _calculate_max_drawdown(equity_curve),
            "sharpe": None
        }

    data = pd.DataFrame(trade_rows)
    wins = data[data["pnl_dollars"] > 0]
    losses = data[data["pnl_dollars"] <= 0]

    gross_profit = float(wins["pnl_dollars"].sum()) if not wins.empty else 0.0
    gross_loss = abs(float(losses["pnl_dollars"].sum())) if not losses.empty else 0.0
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else math.inf
    expectancy = float(data["pnl_dollars"].mean())

    max_drawdown = _calculate_max_drawdown(equity_curve)
    returns = [float(row["equity"]) for row in equity_curve]

    sharpe = None
    if len(returns) > 2:
        equity_series = pd.Series(returns)
        pct_returns = equity_series.pct_change().dropna()
        if not pct_returns.empty and pct_returns.std() > 0:
            sharpe = float((pct_returns.mean() / pct_returns.std()) * math.sqrt(252))

    return {
        "closed_trades": len(data),
        "win_rate": len(wins) / len(data),
        "profit_factor": profit_factor,
        "expectancy": expectancy,
        "average_winner": float(wins["pnl_dollars"].mean()) if not wins.empty else 0.0,
        "average_loser": float(losses["pnl_dollars"].mean()) if not losses.empty else 0.0,
        "max_drawdown": max_drawdown,
        "sharpe": sharpe,
        "best_ticker": _best_group(data, "ticker"),
        "worst_ticker": _worst_group(data, "ticker"),
        "best_time_of_day": _best_time_bucket(data),
        "worst_time_of_day": _worst_time_bucket(data),
        "best_setup": _best_group(data, "setup_type"),
        "worst_setup": _worst_group(data, "setup_type"),
        "losing_streak": _max_losing_streak(data),
        "edge_by_rsi_bucket": _bucket_edge(data, "rsi", [40, 50, 60, 70, 80]),
        "edge_by_rvol_bucket": _bucket_edge(data, "rvol", [1, 1.5, 2, 3]),
        "average_r": _mean_or_zero(data, "r_multiple"),
        "average_hold_time": _mean_or_zero(data, "hold_time_minutes"),
        "median_hold_time": _median_or_zero(data, "hold_time_minutes"),
        "largest_winner": float(wins["pnl_dollars"].max()) if not wins.empty else 0.0,
        "largest_loser": float(losses["pnl_dollars"].min()) if not losses.empty else 0.0,
        "best_trade": _trade_extreme(data, "pnl_dollars", best=True),
        "worst_trade": _trade_extreme(data, "pnl_dollars", best=False),
    }


def print_report(report: dict) -> None:
    print("\nPROFITABILITY REPORT")
    print("--------------------")
    if report.get("closed_trades", 0) == 0:
        print("No closed trades.")
        return

    print(f'Closed trades:       {report["closed_trades"]}')
    print(f'Win rate:            {report["win_rate"] * 100:.2f}%')
    print(f'Profit factor:       {report["profit_factor"]:.2f}')
    print(f'Expectancy/trade:    ${report["expectancy"]:.2f}')
    print(f'Average winner:      ${report["average_winner"]:.2f}')
    print(f'Average loser:       ${report["average_loser"]:.2f}')
    print(f'Max drawdown:        {report["max_drawdown"] * 100:.2f}%')
    if report["sharpe"] is not None:
        print(f'Sharpe estimate:     {report["sharpe"]:.2f}')
    print(f'Best ticker:         {report["best_ticker"]}')
    print(f'Worst ticker:        {report["worst_ticker"]}')
    print(f'Best time of day:    {report["best_time_of_day"]}')
    print(f'Worst time of day:   {report["worst_time_of_day"]}')
    print(f'Max losing streak:   {report["losing_streak"]}')
    print(f'Average R:           {report.get("average_r", 0.0):.2f}')
    if report.get("best_trade"):
        best = report["best_trade"]
        print(f'Best trade:          {best.get("ticker")} ${best.get("pnl_dollars", 0.0):.2f}')
    if report.get("worst_trade"):
        worst = report["worst_trade"]
        print(f'Worst trade:         {worst.get("ticker")} ${worst.get("pnl_dollars", 0.0):.2f}')


def _best_group(data: pd.DataFrame, column: str):
    grouped = data.groupby(column, dropna=False)["pnl_dollars"].sum()
    return grouped.idxmax() if not grouped.empty else None


def _worst_group(data: pd.DataFrame, column: str):
    grouped = data.groupby(column, dropna=False)["pnl_dollars"].sum()
    return grouped.idxmin() if not grouped.empty else None


def _best_time_bucket(data: pd.DataFrame):
    data = data.copy()
    timestamps = data["entry_timestamp"]
    if getattr(timestamps.dt, "tz", None) is not None:
        timestamps = timestamps.dt.tz_convert(EASTERN)
    data["time_bucket"] = timestamps.dt.hour
    return _best_group(data, "time_bucket")


def _worst_time_bucket(data: pd.DataFrame):
    data = data.copy()
    timestamps = data["entry_timestamp"]
    if getattr(timestamps.dt, "tz", None) is not None:
        timestamps = timestamps.dt.tz_convert(EASTERN)
    data["time_bucket"] = timestamps.dt.hour
    return _worst_group(data, "time_bucket")


def _max_losing_streak(data: pd.DataFrame) -> int:
    max_streak = 0
    current_streak = 0

    for pnl in data["pnl_dollars"]:
        if pnl <= 0:
            current_streak += 1
            max_streak = max(max_streak, current_streak)
        else:
            current_streak = 0

    return max_streak


def _calculate_max_drawdown(equity_curve: list[dict]) -> float:
    max_drawdown = 0.0
    peak = None

    for row in equity_curve:
        equity = float(row["equity"])
        if peak is None:
            peak = equity
        peak = max(peak, equity)
        drawdown = (peak - equity) / peak if peak > 0 else 0.0
        max_drawdown = max(max_drawdown, drawdown)

    return max_drawdown


def _bucket_edge(data: pd.DataFrame, column: str, bins: list[float]) -> dict:
    filtered = data.dropna(subset=[column]).copy()
    if filtered.empty:
        return {}
    filtered["bucket"] = pd.cut(filtered[column], bins=bins)
    return filtered.groupby("bucket", observed=False)["pnl_dollars"].mean().to_dict()


def _mean_or_zero(data: pd.DataFrame, column: str) -> float:
    if column not in data.columns:
        return 0.0
    filtered = data.dropna(subset=[column])
    if filtered.empty:
        return 0.0
    return float(filtered[column].mean())


def _median_or_zero(data: pd.DataFrame, column: str) -> float:
    if column not in data.columns:
        return 0.0
    filtered = data.dropna(subset=[column])
    if filtered.empty:
        return 0.0
    return float(filtered[column].median())


def _trade_extreme(data: pd.DataFrame, column: str, best: bool) -> dict | None:
    if data.empty or column not in data.columns:
        return None
    index = data[column].idxmax() if best else data[column].idxmin()
    row = data.loc[index]
    keys = [
        "ticker",
        "entry_timestamp",
        "exit_timestamp",
        "entry_price",
        "exit_price",
        "position_size",
        "pnl_dollars",
        "r_multiple",
        "hold_time_minutes",
        "entry_reason",
        "exit_reason",
    ]
    return {key: row.get(key) for key in keys}
