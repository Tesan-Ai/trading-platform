import math

from analytics.drawdown import analyze_drawdowns
from analytics.monte_carlo import run_monte_carlo
from analytics.research_lab import build_research_lab_report
from analytics.risk_reward import analyze_risk_reward


SAMPLE_TRADES = [
    {
        "ticker": "MSFT",
        "entry_timestamp": "2026-01-02T14:35:00Z",
        "exit_timestamp": "2026-01-02T15:00:00Z",
        "entry_price": 100.0,
        "exit_price": 104.0,
        "position_size": 10,
        "stop_loss": 98.0,
        "take_profit": 104.0,
        "pnl_dollars": 40.0,
        "exit_reason": "2R take profit",
        "spy_trend": "BULL_INTRADAY",
    },
    {
        "ticker": "META",
        "entry_timestamp": "2026-01-03T14:35:00Z",
        "exit_timestamp": "2026-01-03T14:45:00Z",
        "entry_price": 50.0,
        "exit_price": 49.0,
        "position_size": 10,
        "stop_loss": 49.0,
        "take_profit": 52.0,
        "pnl_dollars": -10.0,
        "exit_reason": "stop loss",
        "spy_trend": "RISK_OFF",
    },
    {
        "ticker": "MSFT",
        "entry_timestamp": "2026-01-04T15:35:00Z",
        "exit_timestamp": "2026-01-04T15:55:00Z",
        "entry_price": 100.0,
        "exit_price": 101.0,
        "position_size": 10,
        "stop_loss": 99.0,
        "take_profit": 102.0,
        "pnl_dollars": 10.0,
        "exit_reason": "end of day close",
        "spy_trend": "BULL_INTRADAY",
    },
]

SAMPLE_EQUITY = [
    {"timestamp": "2026-01-02T14:35:00Z", "equity": 10000.0},
    {"timestamp": "2026-01-02T15:00:00Z", "equity": 10040.0},
    {"timestamp": "2026-01-03T14:45:00Z", "equity": 10030.0},
    {"timestamp": "2026-01-04T15:55:00Z", "equity": 10040.0},
]


def test_risk_reward_calculates_r_multiples_and_hit_rates():
    result = analyze_risk_reward(SAMPLE_TRADES)
    assert math.isclose(result["average_r_multiple"], 2 / 3)
    assert result["stop_loss_hit_rate"] == 1 / 3
    assert result["take_profit_hit_rate"] == 1 / 3
    assert result["current_win_rate_clears_breakeven"] is True


def test_drawdown_calculates_peak_to_trough():
    result = analyze_drawdowns(SAMPLE_EQUITY, SAMPLE_TRADES)
    assert math.isclose(result["max_drawdown"], 10 / 10040)
    assert result["peak_equity"] == 10040.0
    assert result["trough_equity"] == 10030.0
    assert len(result["suggestions"]) == 3


def test_monte_carlo_reports_distribution():
    result = run_monte_carlo(SAMPLE_TRADES, starting_equity=10000.0, runs=100, seed=7)
    assert result["runs"] == 100
    assert result["median_ending_equity"] is not None
    assert 0.0 <= result["probability_of_loss"] <= 1.0


def test_research_lab_report_generation_uses_real_sections():
    report = build_research_lab_report(
        strategy_name="opening_range_vwap_momentum_v1",
        profile="conservative",
        start_date="2026-01-01",
        end_date="2026-01-31",
        symbols=["MSFT", "META"],
        market_filters=["SPY", "QQQ"],
        starting_equity=10000.0,
        trade_rows=SAMPLE_TRADES,
        equity_curve=SAMPLE_EQUITY,
        monte_carlo_runs=50,
    )
    assert report["status"] == "RESEARCH_ONLY"
    assert report["backtest"]["closed_trades"] == 3
    assert math.isclose(report["risk_reward"]["average_r_multiple"], 2 / 3)
    assert report["market_regime"]["performance_by_regime"]
    assert report["promotion_recommendation"]["recommendation"] == "Keep RESEARCH_ONLY"
