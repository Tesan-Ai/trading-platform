from strategies.opening_range_vwap_momentum import OpeningRangeVwapMomentumStrategy
from risk.orvwap_risk_engine import OrvwapRiskEngine


def test_stop_loss_uses_tightest_valid_candidate(monkeypatch):
    monkeypatch.setattr("config.ORVWAP_STOP_SELECTION", "tightest")
    strategy = OpeningRangeVwapMomentumStrategy()
    features = {
        "vwap": 99.0,
        "opening_range_midpoint": 98.5,
        "atr_14": 2.0,
    }
    stop = strategy._select_stop_loss(100.0, features)
    assert stop == 98.5


def test_stop_loss_uses_widest_valid_candidate(monkeypatch):
    monkeypatch.setattr("config.ORVWAP_STOP_SELECTION", "widest")
    strategy = OpeningRangeVwapMomentumStrategy()
    features = {
        "vwap": 99.0,
        "opening_range_midpoint": 98.5,
        "atr_14": 2.0,
    }
    stop = strategy._select_stop_loss(100.0, features)
    assert stop == 98.5


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
    assert details["signal_type"] == "buy"
    assert details["passed_all_entry_rules"] is True


def test_rejects_before_opening_range_complete():
    strategy = OpeningRangeVwapMomentumStrategy()
    features = {
        "in_entry_window": True,
        "or_complete": False,
        "or_breakout_close": True,
        "above_vwap": True,
        "volume_ratio": 2.0,
        "spread_percent": 0.05,
        "distance_from_vwap_atr": 0.5,
        "close": 100.0,
    }
    regime = {"trade_allowed": True, "spy_above_vwap": True, "qqq_above_vwap": True}
    passes, details = strategy.evaluate_entry("NVDA", features, regime)
    assert passes is False
    assert details["skip_reason"] == "opening range not complete"


def test_rejects_tech_symbol_when_qqq_below_vwap():
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
        "qqq_above_vwap": False,
        "reason": "SPY above VWAP",
    }
    passes, details = strategy.evaluate_entry("NVDA", features, regime)
    assert passes is False
    assert details["skip_reason"] == "QQQ below VWAP for tech symbol"


def test_risk_engine_sizes_point_three_seven_five_percent(monkeypatch):
    monkeypatch.setattr("config.TRADING_MODE", "PAPER")
    signal = {
        "entry_price": 100.0,
        "stop_price": 99.0,
        "target_price": 102.0,
        "spread": 0.05,
        "distance_from_vwap_atr": 0.5,
    }
    decision = OrvwapRiskEngine().approve_entry(
        equity=10000.0,
        cash=10000.0,
        signal=signal,
        open_positions=[],
    )
    assert decision.approved is True
    assert decision.dollar_risk == 37.5
    assert decision.final_quantity == 37


def test_risk_engine_blocks_live_mode(monkeypatch):
    monkeypatch.setattr("config.TRADING_MODE", "LIVE")
    signal = {
        "entry_price": 100.0,
        "stop_price": 99.0,
        "target_price": 102.0,
    }
    decision = OrvwapRiskEngine().approve_entry(10000.0, 10000.0, signal, [])
    assert decision.approved is False
    assert decision.reason == "paper mode required"
