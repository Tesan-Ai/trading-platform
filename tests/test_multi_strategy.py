from analytics.multi_strategy import build_multi_strategy_report


def _report(strategy_name, expectancy, profit_factor, closed_trades, regime="BULL_INTRADAY"):
    return {
        "strategy_name": strategy_name,
        "status": "RESEARCH_ONLY",
        "validation_gate": {"passes": False},
        "promotion_recommendation": {"recommendation": "Keep RESEARCH_ONLY"},
        "backtest": {
            "closed_trades": closed_trades,
            "total_return": 0.03 if expectancy > 0 else -0.02,
            "profit_factor": profit_factor,
            "expectancy": expectancy,
            "win_rate": 0.55 if expectancy > 0 else 0.35,
            "max_drawdown": 0.02,
        },
        "market_regime": {
            "performance_by_regime": [
                {
                    "name": regime,
                    "closed_trades": closed_trades,
                    "expectancy": expectancy,
                    "win_rate": 0.55 if expectancy > 0 else 0.35,
                    "total_pnl": expectancy * closed_trades,
                }
            ]
        },
    }


def test_multi_strategy_report_ranks_and_recommends_by_regime():
    report = build_multi_strategy_report(
        reports=[
            _report("opening_range_vwap_momentum_v1", expectancy=4.0, profit_factor=1.4, closed_trades=35),
            _report("momentum_breakout_v1", expectancy=-2.0, profit_factor=0.8, closed_trades=40),
        ],
        skipped=[],
        start_date="2026-01-01",
        end_date="2026-01-31",
        profile="conservative",
        symbols_by_strategy={},
        market_filters_by_strategy={},
    )

    assert report["mode"] == "RESEARCH_ONLY"
    assert report["leaderboard"][0]["strategy_name"] == "opening_range_vwap_momentum_v1"
    assert report["strategy_allocator"]["mode"] == "PAPER_CANDIDATE"
    assert report["best_by_regime"][0]["recommended_strategy"] == "opening_range_vwap_momentum_v1"


def test_allocator_stays_shadow_only_when_sample_is_small():
    report = build_multi_strategy_report(
        reports=[_report("opening_range_vwap_momentum_v1", expectancy=8.0, profit_factor=2.0, closed_trades=5)],
        skipped=[],
        start_date="2026-01-01",
        end_date="2026-01-31",
        profile="conservative",
        symbols_by_strategy={},
        market_filters_by_strategy={},
    )

    assert report["strategy_allocator"]["mode"] == "SHADOW_ONLY"
    assert report["strategy_allocator"]["selected_strategy"] is None
