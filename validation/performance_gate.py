import math

import config


BACKTEST_MIN_CLOSED_TRADES = int(getattr(config, "BACKTEST_MIN_CLOSED_TRADES", 30))
BACKTEST_MIN_PROFIT_FACTOR = float(getattr(config, "BACKTEST_MIN_PROFIT_FACTOR", 1.15))
BACKTEST_MIN_EXPECTANCY = float(getattr(config, "BACKTEST_MIN_EXPECTANCY", 0.0))
BACKTEST_MAX_DRAWDOWN = float(getattr(config, "BACKTEST_MAX_DRAWDOWN", 0.08))
BACKTEST_MIN_WIN_RATE = float(getattr(config, "BACKTEST_MIN_WIN_RATE", 0.40))


def evaluate_validation_gate(report: dict, stage: str = "backtest") -> dict:
    """Classify whether a strategy result is good enough for the next platform stage."""
    stage = stage.lower()
    thresholds = _thresholds_for_stage(stage)
    reasons = []

    closed_trades = int(report.get("closed_trades", 0) or 0)
    profit_factor = _finite_float(report.get("profit_factor", 0.0))
    expectancy = _finite_float(report.get("expectancy", 0.0))
    max_drawdown = _finite_float(report.get("max_drawdown", 1.0))
    win_rate = _finite_float(report.get("win_rate", 0.0))

    if closed_trades < thresholds["min_closed_trades"]:
        reasons.append(
            f"needs at least {thresholds['min_closed_trades']} closed trades; got {closed_trades}"
        )
    if profit_factor < thresholds["min_profit_factor"]:
        reasons.append(
            f"profit factor {profit_factor:.2f} below {thresholds['min_profit_factor']:.2f}"
        )
    if expectancy <= thresholds["min_expectancy"]:
        reasons.append(
            f"expectancy ${expectancy:.2f} not above ${thresholds['min_expectancy']:.2f}"
        )
    if max_drawdown > thresholds["max_drawdown"]:
        reasons.append(
            f"max drawdown {max_drawdown * 100:.2f}% above {thresholds['max_drawdown'] * 100:.2f}%"
        )
    if win_rate < thresholds["min_win_rate"]:
        reasons.append(
            f"win rate {win_rate * 100:.2f}% below {thresholds['min_win_rate'] * 100:.2f}%"
        )

    passed = not reasons
    return {
        "stage": stage,
        "passes": passed,
        "status": _status_for_result(stage, passed),
        "reasons": reasons or [f"{stage} validation gate satisfied"],
        "thresholds": thresholds,
        "metrics": {
            "closed_trades": closed_trades,
            "profit_factor": profit_factor,
            "expectancy": expectancy,
            "max_drawdown": max_drawdown,
            "win_rate": win_rate,
        },
    }


def print_validation_gate(gate: dict) -> None:
    print(f"\n{gate['stage'].upper()} VALIDATION GATE")
    print("------------------------")
    print(f"Status:                {gate['status']}")
    print(f"Passes:                {gate['passes']}")
    for reason in gate["reasons"]:
        print(f"- {reason}")


def _thresholds_for_stage(stage: str) -> dict:
    if stage in {"paper", "paper_to_live", "live"}:
        return {
            "min_closed_trades": int(config.MIN_PAPER_TRADES_BEFORE_LIVE),
            "min_profit_factor": float(config.MIN_PROFIT_FACTOR_BEFORE_LIVE),
            "min_expectancy": float(config.MIN_EXPECTANCY_BEFORE_LIVE),
            "max_drawdown": float(config.MAX_VALIDATED_DRAWDOWN),
            "min_win_rate": BACKTEST_MIN_WIN_RATE,
        }

    return {
        "min_closed_trades": BACKTEST_MIN_CLOSED_TRADES,
        "min_profit_factor": BACKTEST_MIN_PROFIT_FACTOR,
        "min_expectancy": BACKTEST_MIN_EXPECTANCY,
        "max_drawdown": BACKTEST_MAX_DRAWDOWN,
        "min_win_rate": BACKTEST_MIN_WIN_RATE,
    }


def _status_for_result(stage: str, passed: bool) -> str:
    if not passed:
        return "RESEARCH_ONLY"
    if stage in {"paper", "paper_to_live", "live"}:
        return "LIVE_CANDIDATE"
    return "PAPER_CANDIDATE"


def _finite_float(value) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return 0.0
    if math.isnan(numeric):
        return 0.0
    if math.isinf(numeric):
        return 999999.0
    return numeric
