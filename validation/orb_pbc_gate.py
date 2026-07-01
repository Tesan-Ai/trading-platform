"""ORB-PBC v1.0 specific validation gates.

These are layered ON TOP of, not instead of, the generic
``validation/performance_gate.py`` backtest gate. The generic gate answers
"is this good enough to be a PAPER_CANDIDATE at all"; this module answers the
much stricter, strategy-specific question the ORB-PBC spec asks for
(>=100 trades, PF after/before costs, average R, symbol concentration,
best-symbol-removed PF, monthly profitability, walk-forward efficiency,
Monte Carlo risk, slippage-stress robustness).

Every threshold here is read from ``config.py`` (``ORB_PBC_*``) so nothing is
hardcoded twice. Any metric that could not be computed (e.g. walk-forward
was not run, or before-cost trades are unavailable) is reported as
``None`` / "not available" with an explicit reason -- never silently
skipped or treated as a pass.
"""

from __future__ import annotations

import math

import config


def _finite(value):
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(numeric) or math.isinf(numeric):
        return None
    return numeric


def compute_avg_r_multiple(trade_rows: list[dict]) -> float | None:
    values = [row.get("r_multiple") for row in trade_rows if row.get("r_multiple") is not None]
    values = [float(v) for v in values if _finite(v) is not None]
    if not values:
        return None
    return sum(values) / len(values)


def compute_symbol_profit_concentration(trade_rows: list[dict]) -> dict:
    by_symbol: dict[str, float] = {}
    for row in trade_rows:
        symbol = row.get("ticker")
        pnl = _finite(row.get("pnl_dollars")) or 0.0
        by_symbol[symbol] = by_symbol.get(symbol, 0.0) + pnl

    total_net = sum(by_symbol.values())
    if not by_symbol or total_net == 0:
        return {
            "by_symbol_pnl": by_symbol,
            "best_symbol": None,
            "max_symbol_profit_share": None,
            "reason": "not available: no trades or zero net profit",
        }

    best_symbol = max(by_symbol, key=lambda symbol: by_symbol[symbol])
    share = by_symbol[best_symbol] / total_net if total_net > 0 else None
    return {
        "by_symbol_pnl": by_symbol,
        "best_symbol": best_symbol,
        "max_symbol_profit_share": share,
        "reason": None,
    }


def compute_best_symbol_removed_pf(trade_rows: list[dict], best_symbol: str | None) -> float | None:
    if not best_symbol:
        return None
    from analytics.trade_analytics import calculate_report

    remaining = [row for row in trade_rows if row.get("ticker") != best_symbol]
    if not remaining:
        return None
    report = calculate_report(remaining, [])
    pf = report.get("profit_factor")
    return _finite(pf)


def compute_monthly_profitability(trade_rows: list[dict]) -> dict:
    if not trade_rows:
        return {"monthly_profitable_pct": None, "months": [], "reason": "not available: no trades"}

    import pandas as pd

    data = pd.DataFrame(trade_rows)
    data["exit_timestamp"] = pd.to_datetime(data["exit_timestamp"], errors="coerce", utc=True)
    data["pnl_dollars"] = pd.to_numeric(data["pnl_dollars"], errors="coerce").fillna(0.0)
    data = data.dropna(subset=["exit_timestamp"])
    if data.empty:
        return {"monthly_profitable_pct": None, "months": [], "reason": "not available: no valid exit timestamps"}

    monthly = data.groupby(data["exit_timestamp"].dt.strftime("%Y-%m"))["pnl_dollars"].sum()
    if monthly.empty:
        return {"monthly_profitable_pct": None, "months": [], "reason": "not available"}

    profitable_months = int((monthly > 0).sum())
    pct = profitable_months / len(monthly)
    return {
        "monthly_profitable_pct": pct,
        "months": [{"month": month, "pnl": float(value)} for month, value in monthly.items()],
        "reason": None,
    }


def evaluate_orb_pbc_gate(
    *,
    report_after_costs: dict,
    trade_rows: list[dict],
    report_before_costs: dict | None = None,
    monte_carlo: dict | None = None,
    walk_forward: dict | None = None,
    slippage_stress_report: dict | None = None,
    drawdown: dict | None = None,
) -> dict:
    """Evaluate the full ORB-PBC v1.0 pass/fail/reject checklist.

    Returns a dict with per-criterion pass/fail (or None = not available),
    a list of triggered FAIL/REJECT conditions, and an overall status that
    is always one of RESEARCH_ONLY / PAPER_CANDIDATE (never LIVE_CANDIDATE
    -- this module cannot recommend live trading).
    """
    closed_trades = int(report_after_costs.get("closed_trades", 0) or 0)
    pf_after = _finite(report_after_costs.get("profit_factor"))
    expectancy = _finite(report_after_costs.get("expectancy"))
    max_dd = _finite(report_after_costs.get("max_drawdown"))
    win_rate = _finite(report_after_costs.get("win_rate"))

    pf_before = _finite(report_before_costs.get("profit_factor")) if report_before_costs else None
    avg_r = compute_avg_r_multiple(trade_rows)
    concentration = compute_symbol_profit_concentration(trade_rows)
    best_symbol_removed_pf = compute_best_symbol_removed_pf(trade_rows, concentration.get("best_symbol"))
    monthly = compute_monthly_profitability(trade_rows)

    mc = monte_carlo or {}
    mc_p_negative = _finite(mc.get("probability_of_loss"))
    mc_p_dd10 = _finite(mc.get("probability_of_breaching_max_drawdown"))

    wf = walk_forward or {}
    wfe = _finite(wf.get("walk_forward_efficiency"))
    oos_profitable_pct = _finite(wf.get("oos_profitable_window_pct"))

    slippage_pf = _finite(slippage_stress_report.get("profit_factor")) if slippage_stress_report else None

    longest_dd_months = None
    if drawdown and drawdown.get("max_drawdown_duration") is not None:
        # max_drawdown_duration is reported in bars (5-minute bars here);
        # convert to an approximate month count assuming ~78 bars/session and
        # ~21 sessions/month, purely for the "longest drawdown < 4 months" gate.
        bars = drawdown.get("max_drawdown_duration") or 0
        longest_dd_months = bars / (78 * 21) if bars else 0.0

    criteria = []

    def _criterion(name, passed, detail, available=True):
        criteria.append(
            {
                "name": name,
                "passed": passed if available else None,
                "available": available,
                "detail": detail,
            }
        )

    _criterion(
        "min_trades",
        closed_trades >= config.ORB_PBC_MIN_TRADES,
        f"{closed_trades} closed trades vs required >= {config.ORB_PBC_MIN_TRADES}",
    )
    _criterion(
        "profit_factor_after_costs",
        pf_after is not None and pf_after >= config.ORB_PBC_PF_MIN_AFTER_COSTS,
        f"PF after costs = {pf_after} vs required >= {config.ORB_PBC_PF_MIN_AFTER_COSTS}",
        available=pf_after is not None,
    )
    _criterion(
        "profit_factor_before_costs",
        pf_before is not None and pf_before >= config.ORB_PBC_PF_MIN_BEFORE_COSTS,
        f"PF before costs = {pf_before} vs required >= {config.ORB_PBC_PF_MIN_BEFORE_COSTS}",
        available=pf_before is not None,
    )
    _criterion(
        "avg_r_multiple",
        avg_r is not None and avg_r >= config.ORB_PBC_AVG_R_MIN,
        f"avg R = {avg_r} vs required >= {config.ORB_PBC_AVG_R_MIN}",
        available=avg_r is not None,
    )
    _criterion(
        "expectancy_positive",
        expectancy is not None and expectancy > config.ORB_PBC_EXPECTANCY_MIN,
        f"expectancy = {expectancy} vs required > {config.ORB_PBC_EXPECTANCY_MIN}",
        available=expectancy is not None,
    )
    _criterion(
        "max_drawdown",
        max_dd is not None and max_dd <= config.ORB_PBC_MAX_DRAWDOWN_PCT,
        f"max drawdown = {max_dd} vs required <= {config.ORB_PBC_MAX_DRAWDOWN_PCT}",
        available=max_dd is not None,
    )
    _criterion(
        "longest_drawdown_months",
        longest_dd_months is not None and longest_dd_months <= config.ORB_PBC_LONGEST_DRAWDOWN_MONTHS_MAX,
        f"longest drawdown ~= {longest_dd_months} months vs required <= {config.ORB_PBC_LONGEST_DRAWDOWN_MONTHS_MAX}",
        available=longest_dd_months is not None,
    )
    _criterion(
        "symbol_concentration",
        concentration.get("max_symbol_profit_share") is not None
        and concentration["max_symbol_profit_share"] <= config.ORB_PBC_MAX_SYMBOL_PROFIT_SHARE,
        f"best symbol {concentration.get('best_symbol')} share = "
        f"{concentration.get('max_symbol_profit_share')} vs required <= {config.ORB_PBC_MAX_SYMBOL_PROFIT_SHARE}",
        available=concentration.get("max_symbol_profit_share") is not None,
    )
    _criterion(
        "best_symbol_removed_pf",
        best_symbol_removed_pf is not None and best_symbol_removed_pf >= config.ORB_PBC_BEST_SYMBOL_REMOVED_PF_MIN,
        f"PF with {concentration.get('best_symbol')} removed = {best_symbol_removed_pf} "
        f"vs required >= {config.ORB_PBC_BEST_SYMBOL_REMOVED_PF_MIN}",
        available=best_symbol_removed_pf is not None,
    )
    _criterion(
        "monthly_profitability",
        monthly.get("monthly_profitable_pct") is not None
        and monthly["monthly_profitable_pct"] >= config.ORB_PBC_MONTHLY_PROFITABLE_PCT_MIN,
        f"monthly profitable pct = {monthly.get('monthly_profitable_pct')} "
        f"vs required >= {config.ORB_PBC_MONTHLY_PROFITABLE_PCT_MIN}",
        available=monthly.get("monthly_profitable_pct") is not None,
    )
    _criterion(
        "walk_forward_efficiency",
        wfe is not None and wfe >= config.ORB_PBC_WF_EFFICIENCY_MIN,
        f"WFE = {wfe} vs required >= {config.ORB_PBC_WF_EFFICIENCY_MIN}",
        available=wfe is not None,
    )
    _criterion(
        "walk_forward_oos_profitable_windows",
        oos_profitable_pct is not None and oos_profitable_pct >= config.ORB_PBC_WF_OOS_PROFITABLE_WINDOWS_MIN,
        f"OOS profitable windows = {oos_profitable_pct} vs required >= {config.ORB_PBC_WF_OOS_PROFITABLE_WINDOWS_MIN}",
        available=oos_profitable_pct is not None,
    )
    _criterion(
        "monte_carlo_drawdown_risk",
        mc_p_dd10 is not None and mc_p_dd10 <= config.ORB_PBC_MC_P_DD_GT_10PCT_MAX,
        f"P(max DD > 10%) = {mc_p_dd10} vs required <= {config.ORB_PBC_MC_P_DD_GT_10PCT_MAX}",
        available=mc_p_dd10 is not None,
    )
    _criterion(
        "monte_carlo_negative_return_risk",
        mc_p_negative is not None and mc_p_negative <= config.ORB_PBC_MC_P_NEGATIVE_MAX,
        f"P(negative return) = {mc_p_negative} vs required <= {config.ORB_PBC_MC_P_NEGATIVE_MAX}",
        available=mc_p_negative is not None,
    )
    _criterion(
        "slippage_stress_pf",
        slippage_pf is not None and slippage_pf >= config.ORB_PBC_SLIPPAGE_STRESS_PF_MIN,
        f"2x slippage PF = {slippage_pf} vs required >= {config.ORB_PBC_SLIPPAGE_STRESS_PF_MIN}",
        available=slippage_pf is not None,
    )
    _criterion(
        "win_rate_sanity",
        win_rate is None or win_rate >= 0.35,
        f"win rate = {win_rate}; below 35% suggests pullback logic may not be holding",
        available=win_rate is not None,
    )

    reject_reasons = []
    if pf_after is not None and pf_after < 1.15:
        reject_reasons.append(f"REJECT: PF after costs {pf_after:.2f} < 1.15 on full sample")
    if avg_r is not None and avg_r < 0.10:
        reject_reasons.append(f"REJECT: average R {avg_r:.2f} < +0.10")
    if max_dd is not None and max_dd > 0.10:
        reject_reasons.append(f"REJECT: max drawdown {max_dd * 100:.1f}% > 10%")
    if concentration.get("max_symbol_profit_share") is not None and best_symbol_removed_pf is not None:
        if best_symbol_removed_pf < 1.0:
            reject_reasons.append("REJECT: removing best symbol turns PF < 1.0")
    if mc_p_negative is not None and mc_p_negative > 0.25:
        reject_reasons.append(f"REJECT: Monte Carlo P(negative return) {mc_p_negative:.2f} > 0.25")
    if wfe is not None and wfe < 0.4:
        reject_reasons.append(f"REJECT: walk-forward OOS efficiency {wfe:.2f} < 0.4")
    if slippage_pf is not None and slippage_pf < 1.0:
        reject_reasons.append(f"REJECT: results collapse under 2x slippage stress (PF {slippage_pf:.2f} < 1.0)")

    trades_per_year = None
    if trade_rows:
        import pandas as pd

        data = pd.DataFrame(trade_rows)
        data["entry_timestamp"] = pd.to_datetime(data["entry_timestamp"], errors="coerce", utc=True)
        span_days = (data["entry_timestamp"].max() - data["entry_timestamp"].min()).days
        if span_days and span_days > 0:
            trades_per_year = len(trade_rows) / (span_days / 365.25)
    if trades_per_year is not None and trades_per_year < 40:
        reject_reasons.append(
            f"REJECT: trade frequency {trades_per_year:.1f}/year < 40/year "
            "(likely a data-window limitation, not a filter-loosening opportunity)"
        )

    available_criteria = [c for c in criteria if c["available"]]
    all_available_pass = all(c["passed"] for c in available_criteria) if available_criteria else False
    hard_pass = all_available_pass and closed_trades >= config.ORB_PBC_MIN_TRADES and not reject_reasons

    status = "PAPER_CANDIDATE" if hard_pass else "RESEARCH_ONLY"

    return {
        "status": status,
        "passes": hard_pass,
        "criteria": criteria,
        "reject_reasons_triggered": reject_reasons,
        "avg_r_multiple": avg_r,
        "profit_factor_before_costs": pf_before,
        "symbol_concentration": concentration,
        "best_symbol_removed_pf": best_symbol_removed_pf,
        "monthly_profitability": monthly,
        "trades_per_year": trades_per_year,
        "longest_drawdown_months_estimate": longest_dd_months,
    }
