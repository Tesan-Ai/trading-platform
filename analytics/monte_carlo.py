from __future__ import annotations

import numpy as np
import pandas as pd


def run_monte_carlo(
    trade_rows: list[dict],
    starting_equity: float,
    runs: int = 1000,
    max_drawdown_threshold: float = 0.08,
    seed: int = 42,
) -> dict:
    if not trade_rows:
        return {
            "runs": runs,
            "median_ending_equity": None,
            "p5_ending_equity": None,
            "p95_ending_equity": None,
            "probability_of_loss": None,
            "probability_of_breaching_max_drawdown": None,
            "worst_simulated_drawdown": None,
            "assessment": "unproven: no closed trades available",
        }

    data = pd.DataFrame(trade_rows)
    pnl = pd.to_numeric(data.get("pnl_dollars"), errors="coerce").dropna().to_numpy(dtype=float)
    if pnl.size == 0:
        return run_monte_carlo([], starting_equity, runs, max_drawdown_threshold, seed)

    rng = np.random.default_rng(seed)
    endings = []
    drawdowns = []
    for _ in range(int(runs)):
        sample = rng.choice(pnl, size=pnl.size, replace=True)
        equity_path = float(starting_equity) + np.cumsum(sample)
        endings.append(float(equity_path[-1]))
        drawdowns.append(_max_drawdown(equity_path, float(starting_equity)))

    endings_array = np.array(endings, dtype=float)
    drawdown_array = np.array(drawdowns, dtype=float)
    probability_of_loss = float(np.mean(endings_array < float(starting_equity)))
    breach_probability = float(np.mean(drawdown_array > float(max_drawdown_threshold)))
    worst_drawdown = float(np.max(drawdown_array))

    return {
        "runs": int(runs),
        "median_ending_equity": float(np.percentile(endings_array, 50)),
        "p5_ending_equity": float(np.percentile(endings_array, 5)),
        "p95_ending_equity": float(np.percentile(endings_array, 95)),
        "probability_of_loss": probability_of_loss,
        "probability_of_breaching_max_drawdown": breach_probability,
        "worst_simulated_drawdown": worst_drawdown,
        "assessment": _assessment(probability_of_loss, breach_probability, len(pnl)),
    }


def _max_drawdown(equity_path: np.ndarray, starting_equity: float) -> float:
    full_path = np.insert(equity_path, 0, starting_equity)
    peaks = np.maximum.accumulate(full_path)
    drawdowns = np.where(peaks > 0, (peaks - full_path) / peaks, 0.0)
    return float(np.max(drawdowns))


def _assessment(probability_of_loss: float, breach_probability: float, trades: int) -> str:
    if trades < 30:
        return "unproven: fewer than 30 closed trades"
    if probability_of_loss > 0.35 or breach_probability > 0.35:
        return "fragile: simulations show elevated loss or drawdown risk"
    if probability_of_loss < 0.15 and breach_probability < 0.20:
        return "robust candidate: simulations are favorable, pending out-of-sample validation"
    return "mixed: usable for research, but not strong enough for promotion by itself"
