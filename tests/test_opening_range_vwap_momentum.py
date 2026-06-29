from strategies.opening_range_vwap_momentum import OpeningRangeVwapMomentumStrategy


def test_stop_loss_uses_tightest_valid_candidate():
    strategy = OpeningRangeVwapMomentumStrategy()
    features = {
        "vwap": 99.0,
        "opening_range_midpoint": 98.5,
        "atr_14": 2.0,
    }
    stop = strategy._select_stop_loss(100.0, features)
    assert stop == 99.6


def test_rejects_symbol_outside_universe():
    strategy = OpeningRangeVwapMomentumStrategy()
    features = {
        "in_entry_window": True,
        "or_complete": True,
        "or_breakout_close": True,
        "above_vwap": True,
        "volume_ratio": 2.0,
        "spread_percent": 0.05,
        "distance_from_vwap_atr": 0.5,
        "close": 100.0,
    }
    regime = {
        "trade_allowed": True,
        "spy_above_vwap": True,
        "qqq_above_vwap": True,
        "reason": "SPY above VWAP",
    }
    passes, details = strategy.evaluate_entry("PLTR", features, regime)
    assert passes is False
    assert details["rejection_reason"] == "symbol outside v1 universe"


def test_accepts_valid_opening_range_breakout():
    strategy = OpeningRangeVwapMomentumStrategy()
    features = {
        "in_entry_window": True,
        "or_complete": True,
        "or_breakout_close": True,
        "above_vwap": True,
        "volume_ratio": 2.0,
        "spread_percent": 0.05,
        "distance_from_vwap_atr": 0.5,
        "close": 100.0,
        "vwap": 99.0,
        "opening_range_midpoint": 98.5,
        "opening_range_high": 99.5,
        "opening_range_low": 98.0,
        "atr_14": 2.0,
        "volume": 10000,
        "volume_avg_20": 4000,
        "vwap_distance": 0.01,
    }
    regime = {
        "trade_allowed": True,
        "spy_above_vwap": True,
        "qqq_above_vwap": True,
        "reason": "SPY above VWAP",
    }
    passes, details = strategy.evaluate_entry("NVDA", features, regime)
    assert passes is True
    assert details["stop_price"] < details["entry_price"] < details["target_price"]
