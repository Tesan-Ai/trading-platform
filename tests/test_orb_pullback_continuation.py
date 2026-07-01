"""Unit tests for the ORB-PBC v1.0 state machine and supporting pure logic.

These tests exercise ``strategies/orb_pullback_continuation.py`` directly,
independent of the backtest engine and of any historical data file, so the
core decision logic (especially "never buy the breakout candle") is verified
in isolation.
"""

from datetime import date, datetime, time, timedelta

import pytest

from strategies.orb_pullback_continuation import (
    ARMED_TRIGGER,
    DONE,
    WAIT_BREAKOUT,
    WAIT_PULLBACK,
    BarSnapshot,
    DailyBook,
    OrbPbcConfig,
    OrbPullbackContinuationStrategy,
    Position,
    Signal,
    SymbolDayState,
    SymbolSnapshot,
    calculate_position_size,
    calculate_stop,
    check_market_filter,
    generate_signal,
    risk_gate_check,
    should_exit,
)

CFG = OrbPbcConfig()


def _bar(end_time, open_, high, low, close):
    return BarSnapshot(end_time=end_time, open=open_, high=high, low=low, close=close, volume=100_000)


def _stock_snapshot(**overrides):
    bar = overrides.pop("last_completed_5m", None) or _bar(time(9, 50), 100.0, 102.0, 99.5, 101.0)
    defaults = dict(
        symbol="NVDA",
        now=time(9, 50),
        current_price=bar.close,
        last_completed_5m=bar,
        vwap=100.5,
        orh=100.8,
        orl=99.0,
        atr_5m=1.0,
        atr_d=3.0,
        prev_close=100.0,
        atr_d_pct=0.03,
        atr_d_pct_p90_1y=0.05,
        atr_5m_p98_20d=5.0,
        ema9_5m=100.6,
        rvol=2.0,
        gap_and_fade_flag=False,
        vwap_cross_count_before_signal=0,
        spread_available=False,
    )
    defaults.update(overrides)
    return SymbolSnapshot(**defaults)


def _index_snapshot(symbol="SPY", **overrides):
    bar = overrides.pop("last_completed_5m", None) or _bar(time(9, 50), 500.0, 502.0, 499.0, 501.0)
    defaults = dict(
        symbol=symbol,
        now=time(9, 50),
        current_price=bar.close,
        last_completed_5m=bar,
        vwap=500.0,
        or_midpoint=500.5,
        orh=501.0,
        orl=500.0,
        atr_d_pct=0.01,
        atr_d_pct_p90_1y=0.02,
    )
    defaults.update(overrides)
    return SymbolSnapshot(**defaults)


# ---------------------------------------------------------------------------
# The core non-negotiable rule: never buy the breakout candle.
# ---------------------------------------------------------------------------


def test_wait_breakout_phase_never_returns_a_signal():
    """No matter how favorable the inputs look, WAIT_BREAKOUT can only ever
    transition to WAIT_PULLBACK; it must never itself produce a Signal."""
    state = SymbolDayState()
    stock = _stock_snapshot(
        current_price=999.0,
        last_completed_5m=_bar(time(9, 50), 100.0, 999.0, 99.0, 999.0),
        rvol=100.0,
    )
    spy = _index_snapshot()
    qqq = _index_snapshot(symbol="QQQ")

    signal = generate_signal(stock, spy, qqq, state, time(9, 50), CFG)

    assert signal is None
    assert state.phase in (WAIT_BREAKOUT, WAIT_PULLBACK)


def test_full_breakout_pullback_trigger_sequence_only_fires_on_final_bar():
    state = SymbolDayState()
    spy = _index_snapshot()
    qqq = _index_snapshot(symbol="QQQ")

    # Bar 1: breakout confirmation bar. Price already far above ORH/VWAP with
    # strong RVOL -- if this strategy "bought the breakout candle" this is
    # exactly where it would fire. It must not.
    breakout_bar = _bar(time(9, 50), 100.5, 102.0, 100.2, 101.0)
    stock1 = _stock_snapshot(last_completed_5m=breakout_bar, current_price=101.0, rvol=2.0)
    signal1 = generate_signal(stock1, spy, qqq, state, time(9, 50), CFG)
    assert signal1 is None
    assert state.phase == WAIT_PULLBACK
    assert state.breakout_confirmations == 1

    # Bar 2: a held pullback -- dips toward EMA9/OR-high reference, closes
    # back above VWAP, holds above the opening range low.
    pullback_bar = _bar(time(9, 55), 100.8, 100.9, 100.4, 100.7)
    stock2 = _stock_snapshot(last_completed_5m=pullback_bar, current_price=100.7, vwap=100.55)
    signal2 = generate_signal(stock2, spy, qqq, state, time(9, 55), CFG)
    assert signal2 is None
    assert state.phase == ARMED_TRIGGER
    assert state.pullback_low == pytest.approx(100.4)
    assert state.pullback_high == pytest.approx(100.9)
    assert state.pullbacks_validated == 1

    # Bar 3: price breaks the pullback bar's high (+ offset) -- THIS is the
    # only bar allowed to fire a signal.
    trigger_bar = _bar(time(10, 0), 100.85, 101.1, 100.8, 101.0)
    stock3 = _stock_snapshot(last_completed_5m=trigger_bar, current_price=101.0, vwap=100.6, rvol=1.4)
    signal3 = generate_signal(stock3, spy, qqq, state, time(10, 0), CFG)

    assert signal3 is not None
    assert isinstance(signal3, Signal)
    assert signal3.side == "LONG"
    assert signal3.entry == pytest.approx(100.9 + CFG.trigger_offset_dollars)
    assert state.triggers_fired == 1


def test_close_below_vwap_during_pullback_invalidates_and_rearms():
    state = SymbolDayState()
    spy = _index_snapshot()
    qqq = _index_snapshot(symbol="QQQ")

    breakout_bar = _bar(time(9, 50), 100.5, 102.0, 100.2, 101.0)
    stock1 = _stock_snapshot(last_completed_5m=breakout_bar, current_price=101.0)
    generate_signal(stock1, spy, qqq, state, time(9, 50), CFG)
    assert state.phase == WAIT_PULLBACK

    failed_bar = _bar(time(9, 55), 100.5, 100.6, 99.8, 99.9)  # closes below vwap
    stock2 = _stock_snapshot(last_completed_5m=failed_bar, current_price=99.9, vwap=100.5)
    signal = generate_signal(stock2, spy, qqq, state, time(9, 55), CFG)

    assert signal is None
    assert state.phase == WAIT_BREAKOUT  # re-armed
    assert state.rearm_count == 1
    assert state.invalidations == 1


def test_rearm_budget_is_exhausted_after_max_rearms():
    cfg = OrbPbcConfig()
    state = SymbolDayState()
    spy = _index_snapshot()
    qqq = _index_snapshot(symbol="QQQ")

    for _ in range(cfg.max_rearms_per_symbol + 1):
        breakout_bar = _bar(time(9, 50), 100.5, 102.0, 100.2, 101.0)
        stock1 = _stock_snapshot(last_completed_5m=breakout_bar, current_price=101.0)
        generate_signal(stock1, spy, qqq, state, time(9, 50), cfg)
        assert state.phase == WAIT_PULLBACK

        failed_bar = _bar(time(9, 55), 100.5, 100.6, 99.8, 99.9)
        stock2 = _stock_snapshot(last_completed_5m=failed_bar, current_price=99.9, vwap=100.5)
        generate_signal(stock2, spy, qqq, state, time(9, 55), cfg)

    assert state.phase == DONE
    assert state.rearm_count == cfg.max_rearms_per_symbol

    # DONE is terminal: further calls never produce a signal.
    breakout_bar = _bar(time(10, 0), 100.5, 102.0, 100.2, 101.0)
    stock = _stock_snapshot(last_completed_5m=breakout_bar, current_price=101.0)
    assert generate_signal(stock, spy, qqq, state, time(10, 0), cfg) is None
    assert state.phase == DONE


def test_max_entries_per_symbol_per_day_blocks_second_signal():
    state = SymbolDayState()
    state.phase = ARMED_TRIGGER
    state.pullback_low = 100.4
    state.pullback_high = 100.9
    state.entries_today = 1  # simulate an entry already opened by the engine

    spy = _index_snapshot()
    qqq = _index_snapshot(symbol="QQQ")
    trigger_bar = _bar(time(10, 0), 100.85, 101.1, 100.8, 101.0)
    stock = _stock_snapshot(last_completed_5m=trigger_bar, current_price=101.0, vwap=100.6, rvol=1.4)

    signal = generate_signal(stock, spy, qqq, state, time(10, 0), CFG)
    assert signal is None


def test_trigger_expires_after_configured_bars_and_falls_back_to_pullback():
    cfg = OrbPbcConfig()
    state = SymbolDayState()
    state.phase = ARMED_TRIGGER
    state.pullback_low = 100.4
    state.pullback_high = 100.9

    spy = _index_snapshot()
    qqq = _index_snapshot(symbol="QQQ")
    quiet_bar = _bar(time(10, 0), 100.5, 100.6, 100.3, 100.5)  # never reaches trigger price
    stock = _stock_snapshot(last_completed_5m=quiet_bar, current_price=100.5)

    for _ in range(cfg.trigger_expiry_bars):
        signal = generate_signal(stock, spy, qqq, state, time(10, 0), cfg)
        assert signal is None

    # One more bar past expiry: retry_count increments and (since
    # max_retries_per_breakout=1) the NEXT expiry re-arms.
    generate_signal(stock, spy, qqq, state, time(10, 0), cfg)
    assert state.phase in (WAIT_PULLBACK, WAIT_BREAKOUT)


# ---------------------------------------------------------------------------
# Market filter
# ---------------------------------------------------------------------------


def test_market_filter_passes_with_favorable_snapshot():
    stock = _stock_snapshot()
    spy = _index_snapshot()
    qqq = _index_snapshot(symbol="QQQ")
    passed, reason = check_market_filter(spy, qqq, stock, time(10, 0), CFG)
    assert passed is True, reason


def test_market_filter_rejects_when_spy_below_vwap():
    stock = _stock_snapshot()
    spy = _index_snapshot(last_completed_5m=_bar(time(9, 50), 500.0, 500.5, 498.0, 499.0))
    qqq = _index_snapshot(symbol="QQQ")
    passed, reason = check_market_filter(spy, qqq, stock, time(10, 0), CFG)
    assert passed is False
    assert "SPY" in reason


def test_market_filter_rejects_outside_signal_window():
    stock = _stock_snapshot()
    spy = _index_snapshot()
    qqq = _index_snapshot(symbol="QQQ")
    passed, reason = check_market_filter(spy, qqq, stock, time(8, 0), CFG)
    assert passed is False
    assert "window" in reason


def test_market_filter_rejects_low_daily_atr_pct():
    stock = _stock_snapshot(atr_d=0.5, prev_close=100.0)  # 0.5% < 1.5% minimum
    spy = _index_snapshot()
    qqq = _index_snapshot(symbol="QQQ")
    passed, reason = check_market_filter(spy, qqq, stock, time(10, 0), CFG)
    assert passed is False
    assert "ATR" in reason


def test_market_filter_rejects_gap_and_fade():
    stock = _stock_snapshot(gap_and_fade_flag=True)
    spy = _index_snapshot()
    qqq = _index_snapshot(symbol="QQQ")
    passed, reason = check_market_filter(spy, qqq, stock, time(10, 0), CFG)
    assert passed is False
    assert "gap" in reason.lower()


def test_market_filter_rejects_excessive_vwap_chop():
    stock = _stock_snapshot(vwap_cross_count_before_signal=5)
    spy = _index_snapshot()
    qqq = _index_snapshot(symbol="QQQ")
    passed, reason = check_market_filter(spy, qqq, stock, time(10, 0), CFG)
    assert passed is False
    assert "cross" in reason.lower()


def test_market_filter_rejects_opening_range_too_narrow():
    stock = _stock_snapshot(orh=100.05, orl=100.0, atr_d=3.0)  # width 0.05 << 0.15*3.0
    spy = _index_snapshot()
    qqq = _index_snapshot(symbol="QQQ")
    passed, reason = check_market_filter(spy, qqq, stock, time(10, 0), CFG)
    assert passed is False
    assert "opening range width" in reason


# ---------------------------------------------------------------------------
# Stop / position sizing
# ---------------------------------------------------------------------------


def test_calculate_stop_uses_documented_min_expression():
    signal = Signal(
        side="LONG", symbol="NVDA", entry=100.91, limit_price=101.0,
        pullback_low=100.4, pullback_high=100.9, trigger_time=time(10, 0),
    )
    atr_5m = 1.0
    stop = calculate_stop(signal, atr_5m, CFG)
    structural = signal.pullback_low - CFG.stop_atr_noise * atr_5m
    floor = signal.entry - CFG.stop_atr_floor * atr_5m
    assert stop == pytest.approx(min(structural, floor))
    assert stop < signal.entry


def test_calculate_stop_rejects_when_distance_exceeds_cap():
    signal = Signal(
        side="LONG", symbol="NVDA", entry=100.0, limit_price=101.0,
        pullback_low=50.0, pullback_high=99.0, trigger_time=time(10, 0),
    )
    stop = calculate_stop(signal, atr_5m=1.0, cfg=CFG)
    assert stop is None


def test_calculate_stop_returns_none_without_atr():
    signal = Signal(
        side="LONG", symbol="NVDA", entry=100.91, limit_price=101.0,
        pullback_low=100.4, pullback_high=100.9, trigger_time=time(10, 0),
    )
    assert calculate_stop(signal, atr_5m=None, cfg=CFG) is None
    assert calculate_stop(signal, atr_5m=0.0, cfg=CFG) is None


def test_calculate_position_size_risk_based():
    shares = calculate_position_size(equity=10_000.0, entry=100.0, stop=99.0, risk_pct=0.005, cfg=CFG)
    # risk_dollars = 50; risk_per_share = 1.0 -> 50 shares
    assert shares == 50


def test_calculate_position_size_zero_risk_per_share_returns_zero():
    assert calculate_position_size(10_000.0, 100.0, 100.0, 0.005, CFG) == 0


# ---------------------------------------------------------------------------
# Exits
# ---------------------------------------------------------------------------


def _dt(hour, minute):
    return datetime.combine(date(2026, 1, 2), time(hour, minute))


def _position(entry=100.0, stop=99.0, shares=50, entry_time=None):
    return Position(
        symbol="NVDA",
        entry_price=entry,
        initial_stop=stop,
        stop=stop,
        shares=shares,
        entry_time=entry_time or _dt(10, 0),
    )


def test_should_exit_eod_flatten_overrides_everything():
    position = _position()
    stock = _stock_snapshot(current_price=105.0)  # deep in profit
    spy = _index_snapshot()
    qqq = _index_snapshot(symbol="QQQ")
    reason = should_exit(position, stock, spy, qqq, _dt(15, 55), CFG)
    assert reason == "EOD_FLATTEN"


def test_should_exit_stop_hit():
    position = _position(entry=100.0, stop=99.0)
    stock = _stock_snapshot(current_price=98.9)
    spy = _index_snapshot()
    qqq = _index_snapshot(symbol="QQQ")
    reason = should_exit(position, stock, spy, qqq, _dt(10, 5), CFG)
    assert reason == "STOP"


def test_should_exit_failed_breakout_close_below_vwap():
    position = _position(entry=100.0, stop=99.0)
    below_vwap_bar = _bar(time(10, 5), 100.0, 100.1, 99.8, 99.95)
    stock = _stock_snapshot(current_price=99.95, vwap=100.0, last_completed_5m=below_vwap_bar)
    spy = _index_snapshot()
    qqq = _index_snapshot(symbol="QQQ")
    reason = should_exit(position, stock, spy, qqq, _dt(10, 5), CFG)
    assert reason == "FAILED_BREAKOUT"


def test_should_exit_scale_half_at_1r_moves_stop_to_breakeven():
    position = _position(entry=100.0, stop=99.0)  # R = 1.0
    profitable_bar = _bar(time(10, 5), 100.5, 101.2, 100.4, 101.1)
    stock = _stock_snapshot(current_price=101.1, vwap=100.2, last_completed_5m=profitable_bar)
    spy = _index_snapshot()
    qqq = _index_snapshot(symbol="QQQ")

    reason = should_exit(position, stock, spy, qqq, _dt(10, 5), CFG)

    assert reason == "SCALE_HALF"
    assert position.scaled is True
    assert position.stop == pytest.approx(100.0 + CFG.breakeven_offset_r * 1.0)


def test_should_exit_time_stop_when_stalling():
    entry_time = _dt(10, 0)
    position = _position(entry=100.0, stop=99.0, entry_time=entry_time)
    stalled_bar = _bar(time(10, 35), 100.1, 100.2, 99.9, 100.1)
    stock = _stock_snapshot(current_price=100.1, vwap=99.9, last_completed_5m=stalled_bar)
    spy = _index_snapshot()
    qqq = _index_snapshot(symbol="QQQ")

    # 35 real minutes later, still well below entry + 0.5R.
    now = entry_time + timedelta(minutes=35)
    reason = should_exit(position, stock, spy, qqq, now, CFG)
    assert reason == "TIME_STOP"


def test_should_exit_trail_ema_after_scale():
    position = _position(entry=100.0, stop=100.1)
    position.scaled = True
    position.highest_high_since_entry = 105.0
    below_ema_bar = _bar(time(10, 30), 104.0, 104.2, 103.0, 103.2)
    stock = _stock_snapshot(current_price=103.2, vwap=101.0, ema9_5m=103.5, atr_5m=1.0, last_completed_5m=below_ema_bar)
    spy = _index_snapshot()
    qqq = _index_snapshot(symbol="QQQ")

    reason = should_exit(position, stock, spy, qqq, _dt(10, 30), CFG)
    assert reason == "TRAIL_EMA"
    # Chandelier stop should have been raised from the initial stop.
    assert position.stop > 100.1


# ---------------------------------------------------------------------------
# Risk gate (supplementary, ORB-PBC-specific rules)
# ---------------------------------------------------------------------------


def test_risk_gate_blocks_correlated_symbol():
    book = DailyBook(start_equity=10_000.0)
    book.open_positions["NVDA"] = _position()
    allowed, reason = risk_gate_check(book, "AMD", CFG, correlated_pairs=[("NVDA", "AMD")])
    assert allowed is False
    assert "correlated" in reason


def test_risk_gate_allows_uncorrelated_symbol():
    book = DailyBook(start_equity=10_000.0)
    book.open_positions["NVDA"] = _position()
    allowed, _ = risk_gate_check(book, "META", CFG, correlated_pairs=[("NVDA", "AMD")])
    assert allowed is True


def test_risk_gate_blocks_after_daily_loss_limit():
    book = DailyBook(start_equity=10_000.0, realized_pnl=-150.0)
    allowed, reason = risk_gate_check(book, "META", CFG, max_daily_loss_pct=0.01)
    assert allowed is False
    assert "daily loss" in reason


def test_risk_gate_blocks_after_two_consecutive_full_stop_losses():
    book = DailyBook(start_equity=10_000.0, consecutive_full_stop_losses=2)
    allowed, reason = risk_gate_check(book, "META", CFG, consecutive_full_stop_loss_limit=2)
    assert allowed is False
    assert "consecutive" in reason.lower()


def test_risk_gate_blocks_at_max_concurrent_positions():
    book = DailyBook(start_equity=10_000.0)
    book.open_positions["NVDA"] = _position()
    book.open_positions["META"] = _position()
    allowed, reason = risk_gate_check(book, "TSLA", CFG, max_concurrent_positions=2)
    assert allowed is False
    assert "concurrent" in reason


# ---------------------------------------------------------------------------
# Long-only guarantee
# ---------------------------------------------------------------------------


def test_strategy_is_long_only_and_registered_as_research_only():
    strategy = OrbPullbackContinuationStrategy()
    assert strategy.side == "long_only"
    assert strategy.research_only is True

    approved, details = strategy.evaluate_entry("NVDA", {}, {})
    assert approved is False
    assert "rejection_reason" in details


def test_signal_side_is_always_long():
    signal = Signal(
        side="LONG", symbol="NVDA", entry=100.0, limit_price=101.0,
        pullback_low=99.0, pullback_high=99.5, trigger_time=time(10, 0),
    )
    assert signal.side == "LONG"
