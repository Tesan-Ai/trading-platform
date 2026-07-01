"""ORB-PBC v1.0 -- Opening Range Breakout Pullback Continuation.

RESEARCH ONLY. This strategy never enables live trading and never bypasses
existing safety gates. See ``config.ORB_PBC_RESEARCH_ONLY``.

Strategy design (source of truth: Fable 5 ORB-PBC v1.0 spec):

    Catalyst-day selection (RVOL) x directional confirmation (ORB) x market
    alignment (SPY/QQQ VWAP) x superior pullback entry x structural stop
    below the pullback low.

The central, non-negotiable behavior is that this strategy NEVER buys the
breakout candle. It confirms a breakout, waits for a held pullback, and only
enters on a break of the pullback bar's high. This file intentionally keeps
the state machine and math as small, pure, unit-testable functions (mirroring
the spec's own pseudocode almost line for line) so the *decision logic* can be
verified independently of any particular backtest engine or data source.

Long-only for v1.0 -- there is no short-entry code path anywhere in this
module. A v1.1 short concept is deliberately not implemented (see the module
docstring at the bottom of this file).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import time as dt_time
from typing import Optional
from zoneinfo import ZoneInfo

import config

EASTERN = ZoneInfo("America/New_York")

WAIT_BREAKOUT = "WAIT_BREAKOUT"
WAIT_PULLBACK = "WAIT_PULLBACK"
ARMED_TRIGGER = "ARMED_TRIGGER"
DONE = "DONE"  # terminal for the day: entered, or exhausted re-arms/retries


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


def _parse_time(value: str) -> dt_time:
    hour, minute = value.split(":")
    return dt_time(int(hour), int(minute))


@dataclass(frozen=True)
class OrbPbcConfig:
    """Immutable snapshot of the ORB-PBC parameters used by the state machine.

    Defaults come from config.py so production defaults and test defaults
    cannot silently drift apart, but tests may construct their own instances
    to exercise edge cases without touching global config.
    """

    opening_range_minutes: int = config.ORB_PBC_OPENING_RANGE_MINUTES
    signal_window_start: dt_time = field(
        default_factory=lambda: _parse_time(config.ORB_PBC_SIGNAL_WINDOW_START)
    )
    signal_window_end: dt_time = field(
        default_factory=lambda: _parse_time(config.ORB_PBC_SIGNAL_WINDOW_END)
    )
    breakout_window_end: dt_time = field(
        default_factory=lambda: _parse_time(config.ORB_PBC_BREAKOUT_WINDOW_END)
    )
    chase_guard_atr: float = config.ORB_PBC_CHASE_GUARD_ATR
    pullback_ref_atr: float = config.ORB_PBC_PULLBACK_REF_ATR
    trigger_offset_dollars: float = config.ORB_PBC_TRIGGER_OFFSET_DOLLARS
    trigger_limit_atr: float = config.ORB_PBC_TRIGGER_LIMIT_ATR
    vwap_extension_max_atr: float = config.ORB_PBC_VWAP_EXTENSION_MAX_ATR
    rvol_breakout_min: float = config.ORB_PBC_RVOL_BREAKOUT_MIN
    rvol_trigger_min: float = config.ORB_PBC_RVOL_TRIGGER_MIN
    spread_pct_max: float = config.ORB_PBC_SPREAD_PCT_MAX
    max_entries_per_symbol_per_day: int = config.ORB_PBC_MAX_ENTRIES_PER_SYMBOL_PER_DAY
    max_rearms_per_symbol: int = config.ORB_PBC_MAX_REARMS_PER_SYMBOL
    trigger_expiry_bars: int = config.ORB_PBC_TRIGGER_EXPIRY_BARS
    max_retries_per_breakout: int = config.ORB_PBC_MAX_RETRIES_PER_BREAKOUT

    stock_atr_d_pct_min: float = config.ORB_PBC_STOCK_ATR_D_PCT_MIN
    or_width_min_atr_d: float = config.ORB_PBC_OR_WIDTH_MIN_ATR_D
    or_width_max_atr_d: float = config.ORB_PBC_OR_WIDTH_MAX_ATR_D
    vwap_cross_count_max: int = config.ORB_PBC_VWAP_CROSS_COUNT_MAX

    stop_atr_floor: float = config.ORB_PBC_STOP_ATR_FLOOR
    stop_atr_noise: float = config.ORB_PBC_STOP_ATR_NOISE
    max_stop_distance_atr: float = config.ORB_PBC_MAX_STOP_DISTANCE_ATR
    scale_out_fraction: float = config.ORB_PBC_SCALE_OUT_FRACTION
    scale_out_at_r: float = config.ORB_PBC_SCALE_OUT_AT_R
    breakeven_after_r: float = config.ORB_PBC_BREAKEVEN_AFTER_R
    breakeven_offset_r: float = config.ORB_PBC_BREAKEVEN_OFFSET_R
    chandelier_multiple: float = config.ORB_PBC_CHANDELIER_MULTIPLE
    time_stop_minutes: float = config.ORB_PBC_TIME_STOP_MINUTES
    time_stop_min_r_to_stay: float = config.ORB_PBC_TIME_STOP_MIN_R_TO_STAY
    eod_flatten_time: dt_time = field(
        default_factory=lambda: _parse_time(config.ORB_PBC_EOD_FLATTEN_TIME)
    )

    risk_per_trade_pct: float = config.ORB_PBC_RISK_PER_TRADE_PCT


DEFAULT_CONFIG = OrbPbcConfig()


# ---------------------------------------------------------------------------
# Snapshots (thin, attribute-based views over indicator data for a given bar)
# ---------------------------------------------------------------------------


@dataclass
class BarSnapshot:
    end_time: object
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0


@dataclass
class SymbolSnapshot:
    """Everything the state machine needs to know about a symbol at "now"."""

    symbol: str
    now: object
    current_price: float
    last_completed_5m: BarSnapshot
    vwap: float
    orh: Optional[float] = None
    orl: Optional[float] = None
    or_midpoint: Optional[float] = None
    or_width: Optional[float] = None
    ema9_5m: Optional[float] = None
    atr_5m: Optional[float] = None
    atr_d: Optional[float] = None
    prev_close: Optional[float] = None
    atr_d_pct: Optional[float] = None
    atr_d_pct_p90_1y: Optional[float] = None
    atr_5m_p98_20d: Optional[float] = None
    rvol: Optional[float] = None
    gap_and_fade_flag: bool = False
    vwap_cross_count_before_signal: int = 0
    spread_pct: Optional[float] = None
    spread_available: bool = True
    has_open_position: bool = False

    @property
    def close_5m(self) -> float:
        return self.last_completed_5m.close


@dataclass
class Signal:
    side: str  # "LONG" only in v1.0
    symbol: str
    entry: float
    limit_price: float
    pullback_low: float
    pullback_high: float
    trigger_time: object
    reason: str = "pullback continuation trigger"


# ---------------------------------------------------------------------------
# Per symbol / per day state
# ---------------------------------------------------------------------------


@dataclass
class SymbolDayState:
    phase: str = WAIT_BREAKOUT
    high_since_breakout: Optional[float] = None
    breakout_bar: Optional[BarSnapshot] = None
    pullback_low: Optional[float] = None
    pullback_high: Optional[float] = None
    bars_armed: int = 0
    retry_count: int = 0
    rearm_count: int = 0
    entries_today: int = 0
    breakout_confirmations: int = 0
    pullbacks_validated: int = 0
    triggers_fired: int = 0
    invalidations: int = 0

    def rearm_or_reset(self, max_rearms: int) -> None:
        """Invalidate the current breakout/pullback attempt.

        Per spec: "go back to WAIT_BREAKOUT ... allow max 2 breakout re-arms
        per symbol per day." Once the re-arm budget is exhausted the symbol
        is done trading for the day (no further breakout attempts).
        """
        self.invalidations += 1
        if self.rearm_count >= max_rearms:
            self.phase = DONE
            return
        self.rearm_count += 1
        self.phase = WAIT_BREAKOUT
        self.high_since_breakout = None
        self.breakout_bar = None
        self.pullback_low = None
        self.pullback_high = None
        self.bars_armed = 0
        self.retry_count = 0

    @property
    def has_entered_today(self) -> bool:
        return self.entries_today > 0


# ---------------------------------------------------------------------------
# Market filter (pre-trade regime + stock gating)
# ---------------------------------------------------------------------------


def check_market_filter(spy: SymbolSnapshot, qqq: SymbolSnapshot, stock: SymbolSnapshot, now, cfg: OrbPbcConfig = DEFAULT_CONFIG) -> tuple[bool, str]:
    """Direct translation of the spec's ``check_market_filter`` pseudocode.

    Returns (passed, reason). SPY/QQQ "agreement" is enforced structurally:
    both indices are individually required to close above their own VWAP, so
    a disagreement (one up, one down relative to VWAP) can never pass both
    checks simultaneously.
    """
    now_time = _as_time(now)
    if not (cfg.signal_window_start <= now_time <= cfg.signal_window_end):
        return False, "outside signal window (09:45-11:15 ET)"

    if spy.close_5m <= spy.vwap:
        return False, "SPY below VWAP"
    if qqq.close_5m <= qqq.vwap:
        return False, "QQQ below VWAP"
    if spy.or_midpoint is not None and spy.close_5m <= spy.or_midpoint:
        return False, "SPY below opening range midpoint"

    if stock.atr_d is None or not stock.prev_close:
        return False, "stock daily ATR/prev close not available"
    if (stock.atr_d / stock.prev_close) < cfg.stock_atr_d_pct_min:
        return False, "stock ATR%% below minimum volatility threshold"

    if stock.atr_5m is not None and stock.atr_5m_p98_20d is not None:
        if stock.atr_5m > stock.atr_5m_p98_20d:
            return False, "5-minute ATR in top 2% of 20-day distribution (chaos filter)"

    if stock.orh is None or stock.orl is None or stock.atr_d is None:
        return False, "opening range or ATR data not available"
    or_width = stock.orh - stock.orl
    if not (cfg.or_width_min_atr_d * stock.atr_d <= or_width <= cfg.or_width_max_atr_d * stock.atr_d):
        return False, "opening range width outside sanity bounds"

    if stock.gap_and_fade_flag:
        return False, "gap-and-fade blacklist"

    if stock.vwap_cross_count_before_signal > cfg.vwap_cross_count_max:
        return False, "too many VWAP crosses before signal (chop filter)"

    if spy.atr_d_pct is not None and spy.atr_d_pct_p90_1y is not None:
        if spy.atr_d_pct > spy.atr_d_pct_p90_1y:
            return False, "SPY daily ATR%% above its 90th percentile (regime too volatile)"

    return True, "market filter passed"


def _as_time(value) -> dt_time:
    """Extract the ET wall-clock time from a naive time, or a tz-aware timestamp.

    Bar/now values may arrive as UTC-aware pandas Timestamps (e.g.
    ``BarSnapshot.end_time`` comes straight from the feature frame's UTC
    ``timestamp`` column). Comparing a UTC wall-clock time against ET-based
    window boundaries (09:45, 11:00, 11:15, 15:50) would silently misalign
    signals by the UTC/ET offset, so any tz-aware value is explicitly
    converted to Eastern first.
    """
    if isinstance(value, dt_time):
        return value
    if getattr(value, "tzinfo", None) is not None:
        return value.astimezone(EASTERN).time()
    return value.time()


# ---------------------------------------------------------------------------
# State machine: WAIT_BREAKOUT -> WAIT_PULLBACK -> ARMED_TRIGGER
# ---------------------------------------------------------------------------


def generate_signal(
    stock: SymbolSnapshot,
    spy: SymbolSnapshot,
    qqq: SymbolSnapshot,
    state: SymbolDayState,
    now,
    cfg: OrbPbcConfig = DEFAULT_CONFIG,
) -> Optional[Signal]:
    """Advance the per-symbol-per-day state machine by one completed 5m bar.

    THE BREAKOUT CANDLE ITSELF NEVER PRODUCES A SIGNAL. Confirming a
    breakout only transitions WAIT_BREAKOUT -> WAIT_PULLBACK; a signal can
    only be produced later, from ARMED_TRIGGER, once price breaks back above
    the *pullback* bar's high.
    """
    if state.phase == DONE:
        return None

    bar = stock.last_completed_5m

    if state.phase == WAIT_BREAKOUT:
        bar_time = _as_time(bar.end_time)
        if (
            cfg.signal_window_start <= bar_time <= cfg.breakout_window_end
            and bar.close > (stock.orh or float("inf"))
            and bar.close > stock.vwap
            and (stock.rvol or 0.0) >= cfg.rvol_breakout_min
        ):
            state.phase = WAIT_PULLBACK
            state.high_since_breakout = bar.high
            state.breakout_bar = bar
            state.breakout_confirmations += 1
        return None

    if state.phase == WAIT_PULLBACK:
        state.high_since_breakout = max(state.high_since_breakout or bar.high, bar.high)

        if bar.close < stock.vwap:
            state.rearm_or_reset(cfg.max_rearms_per_symbol)
            return None

        if stock.atr_5m and state.high_since_breakout > (stock.orh or 0.0) + cfg.chase_guard_atr * stock.atr_5m:
            state.rearm_or_reset(cfg.max_rearms_per_symbol)
            return None

        reference = max(
            stock.ema9_5m if stock.ema9_5m is not None else float("-inf"),
            (stock.orh - cfg.pullback_ref_atr * stock.atr_5m)
            if stock.orh is not None and stock.atr_5m is not None
            else float("-inf"),
        )
        if bar.low <= reference and bar.close >= stock.vwap and bar.low > (stock.orl if stock.orl is not None else float("-inf")):
            state.phase = ARMED_TRIGGER
            state.pullback_low = bar.low
            state.pullback_high = bar.high
            state.bars_armed = 0
            state.pullbacks_validated += 1
        return None

    if state.phase == ARMED_TRIGGER:
        state.bars_armed += 1
        if state.bars_armed > cfg.trigger_expiry_bars:
            state.phase = WAIT_PULLBACK
            state.retry_count += 1
            if state.retry_count > cfg.max_retries_per_breakout:
                state.rearm_or_reset(cfg.max_rearms_per_symbol)
            return None

        trigger = state.pullback_high + cfg.trigger_offset_dollars
        if stock.current_price >= trigger:
            filter_passed, _reason = check_market_filter(spy, qqq, stock, now, cfg)
            spread_ok = (not stock.spread_available) or (
                stock.spread_pct is not None and stock.spread_pct <= cfg.spread_pct_max
            )
            vwap_extension_ok = (
                stock.atr_5m
                and stock.atr_5m > 0
                and ((stock.current_price - stock.vwap) / stock.atr_5m) <= cfg.vwap_extension_max_atr
            )
            if (
                filter_passed
                and stock.current_price > stock.vwap
                and vwap_extension_ok
                and spread_ok
                and (stock.rvol or 0.0) >= cfg.rvol_trigger_min
                and not stock.has_open_position
                and not state.has_entered_today
                and state.entries_today < cfg.max_entries_per_symbol_per_day
            ):
                state.triggers_fired += 1
                limit_price = trigger + cfg.trigger_limit_atr * (stock.atr_5m or 0.0)
                return Signal(
                    side="LONG",
                    symbol=stock.symbol,
                    entry=trigger,
                    limit_price=limit_price,
                    pullback_low=state.pullback_low,
                    pullback_high=state.pullback_high,
                    trigger_time=now,
                )
        return None

    return None


# ---------------------------------------------------------------------------
# Stop / position sizing
# ---------------------------------------------------------------------------


def calculate_stop(signal: Signal, atr_5m: float, cfg: OrbPbcConfig = DEFAULT_CONFIG) -> Optional[float]:
    """Structural pullback stop with an ATR noise floor.

    The source spec expression is implemented literally:

        stop = min(pullback_low - 0.05*ATR5m, entry - 0.6*ATR5m)

    Interpretation note (surfaced per instructions rather than silently
    "fixed"): for a long trade this ``min()`` picks whichever candidate is
    FARTHER below entry (i.e. the wider/more conservative stop), not the
    tighter one. In the common case pullback_low is close to but above
    entry - 0.6*ATR, so ``entry - 0.6*ATR`` is usually the lower (farther)
    value and wins the ``min()``. That means the "0.6 ATR floor" behaves as
    a *minimum stop distance* (never tighter than 0.6 ATR) rather than a
    ceiling, which matches the prose description in the spec
    ("never tighter than 0.6 ATR"). We keep the exact min() expression as
    given rather than substituting max(), and report this explicitly.
    """
    if atr_5m is None or atr_5m <= 0:
        return None
    structural = signal.pullback_low - cfg.stop_atr_noise * atr_5m
    floor = signal.entry - cfg.stop_atr_floor * atr_5m
    stop = min(structural, floor)
    if signal.entry - stop > cfg.max_stop_distance_atr * atr_5m:
        return None
    return stop


def calculate_position_size(
    equity: float,
    entry: float,
    stop: float,
    risk_pct: float = None,
    cfg: OrbPbcConfig = DEFAULT_CONFIG,
) -> int:
    risk_pct = cfg.risk_per_trade_pct if risk_pct is None else risk_pct
    risk_per_share = abs(entry - stop)
    if risk_per_share <= 0:
        return 0
    risk_dollars = equity * risk_pct
    import math

    return int(math.floor(risk_dollars / risk_per_share))


# ---------------------------------------------------------------------------
# Position / exits
# ---------------------------------------------------------------------------


@dataclass
class Position:
    symbol: str
    entry_price: float
    initial_stop: float
    stop: float
    shares: int
    entry_time: object
    highest_high_since_entry: float = None
    scaled: bool = False
    remaining_fraction: float = 1.0
    remaining_shares: int = None

    def __post_init__(self):
        if self.highest_high_since_entry is None:
            self.highest_high_since_entry = self.entry_price
        if self.remaining_shares is None:
            self.remaining_shares = self.shares

    @property
    def risk_per_share(self) -> float:
        return self.entry_price - self.initial_stop


def should_exit(
    position: Position,
    stock: SymbolSnapshot,
    spy: SymbolSnapshot,
    qqq: SymbolSnapshot,
    now,
    cfg: OrbPbcConfig = DEFAULT_CONFIG,
) -> Optional[str]:
    """Direct translation of the spec's ``should_exit`` pseudocode.

    Mutates ``position`` in place for scale-out / breakeven / trailing-stop
    bookkeeping, matching the reference pseudocode's side effects.
    """
    r = position.risk_per_share
    now_time = _as_time(now)

    if now_time >= cfg.eod_flatten_time:
        return "EOD_FLATTEN"

    position.highest_high_since_entry = max(position.highest_high_since_entry, stock.current_price)

    if stock.current_price <= position.stop:
        return "STOP"

    if not position.scaled and stock.close_5m < stock.vwap:
        return "FAILED_BREAKOUT"

    if not position.scaled and spy.close_5m < spy.vwap and qqq.close_5m < qqq.vwap:
        return "MARKET_FILTER_FAIL"

    holding_minutes = _minutes_between(position.entry_time, now)
    if (
        not position.scaled
        and r > 0
        and holding_minutes >= cfg.time_stop_minutes
        and stock.current_price < position.entry_price + cfg.time_stop_min_r_to_stay * r
    ):
        return "TIME_STOP"

    if not position.scaled and r > 0 and stock.current_price >= position.entry_price + cfg.scale_out_at_r * r:
        position.scaled = True
        position.remaining_fraction = 1.0 - config.ORB_PBC_SCALE_OUT_FRACTION
        position.stop = position.entry_price + cfg.breakeven_offset_r * r
        return "SCALE_HALF"

    if position.scaled and stock.atr_5m:
        chandelier = position.highest_high_since_entry - cfg.chandelier_multiple * stock.atr_5m
        position.stop = max(position.stop, chandelier)
        if stock.close_5m < stock.ema9_5m:
            return "TRAIL_EMA"

    return None


def _minutes_between(start, end) -> float:
    delta = end - start
    return delta.total_seconds() / 60.0


# ---------------------------------------------------------------------------
# Risk gate (supplementary checks; layered ON TOP of risk.risk_gate.RiskGate,
# never bypassing it -- see backtesting/orb_pbc_engine.py for how the two are
# combined).
# ---------------------------------------------------------------------------


@dataclass
class DailyBook:
    realized_pnl: float = 0.0
    start_equity: float = 0.0
    trade_count: int = 0
    consecutive_full_stop_losses: int = 0
    open_positions: dict = field(default_factory=dict)  # symbol -> Position

    def has_open_position_in_any(self, symbols) -> bool:
        return any(symbol in self.open_positions for symbol in symbols)


def risk_gate_check(
    book: DailyBook,
    symbol: str,
    cfg: OrbPbcConfig = DEFAULT_CONFIG,
    correlated_pairs=None,
    max_daily_loss_pct: float = None,
    max_trades_per_day: int = None,
    max_concurrent_positions: int = None,
    consecutive_full_stop_loss_limit: int = None,
) -> tuple[bool, str]:
    """Supplementary, ORB-PBC-specific risk checks: correlation cap and the
    2-consecutive-full-stop-loss daily cooldown. Daily loss / trade-count /
    concurrency limits are also re-checked here for unit-test purposes, but
    in the actual backtest engine those three are enforced by (and must
    agree with) ``risk.risk_gate.RiskGate.can_trade()`` -- this function does
    not replace that gate, it adds to it.
    """
    correlated_pairs = correlated_pairs if correlated_pairs is not None else config.ORB_PBC_CORRELATED_PAIRS
    max_daily_loss_pct = (
        config.ORB_PBC_MAX_DAILY_LOSS_PCT if max_daily_loss_pct is None else max_daily_loss_pct
    )
    max_trades_per_day = (
        config.ORB_PBC_MAX_TRADES_PER_DAY if max_trades_per_day is None else max_trades_per_day
    )
    max_concurrent_positions = (
        config.ORB_PBC_MAX_CONCURRENT_POSITIONS
        if max_concurrent_positions is None
        else max_concurrent_positions
    )
    consecutive_full_stop_loss_limit = (
        config.ORB_PBC_CONSECUTIVE_FULL_STOP_LOSSES_LIMIT
        if consecutive_full_stop_loss_limit is None
        else consecutive_full_stop_loss_limit
    )

    if book.start_equity > 0 and book.realized_pnl <= -max_daily_loss_pct * book.start_equity:
        return False, "max daily loss hit"
    if book.trade_count >= max_trades_per_day:
        return False, "max trades per day hit"
    if len(book.open_positions) >= max_concurrent_positions:
        return False, "max concurrent positions hit"
    if book.consecutive_full_stop_losses >= consecutive_full_stop_loss_limit:
        return False, "two consecutive full-stop losses; done for the day"

    for pair in correlated_pairs:
        if symbol in pair and book.has_open_position_in_any(pair):
            return False, f"correlated symbol already open ({'/'.join(pair)})"

    return True, "allowed"


# ---------------------------------------------------------------------------
# Snapshot construction helpers (shared by the backtest engine and tests)
# ---------------------------------------------------------------------------


def bar_from_row(row) -> BarSnapshot:
    return BarSnapshot(
        end_time=row["timestamp"],
        open=float(row["open"]),
        high=float(row["high"]),
        low=float(row["low"]),
        close=float(row["close"]),
        volume=float(row.get("volume", 0.0)),
    )


def snapshot_from_row(
    symbol: str,
    row,
    now=None,
    current_price: float = None,
    spread_pct: Optional[float] = None,
    spread_available: bool = False,
    has_open_position: bool = False,
) -> SymbolSnapshot:
    """Build a SymbolSnapshot from one row of the ORB-PBC 5-minute feature frame."""
    bar = bar_from_row(row)
    resolved_price = bar.close if current_price is None else current_price

    def _get(name):
        value = row.get(name)
        if value is None:
            return None
        try:
            if value != value:  # NaN check without importing numpy/pandas here
                return None
        except TypeError:
            pass
        return value

    return SymbolSnapshot(
        symbol=symbol,
        now=now if now is not None else row["timestamp"],
        current_price=float(resolved_price),
        last_completed_5m=bar,
        vwap=float(_get("vwap")) if _get("vwap") is not None else float("nan"),
        orh=_get("orh"),
        orl=_get("orl"),
        or_midpoint=_get("or_midpoint"),
        or_width=_get("or_width"),
        ema9_5m=_get("ema9_5m"),
        atr_5m=_get("atr_5m"),
        atr_d=_get("atr_d"),
        prev_close=_get("prev_close"),
        atr_d_pct=_get("atr_d_pct"),
        atr_d_pct_p90_1y=_get("atr_d_pct_p90_1y"),
        atr_5m_p98_20d=_get("atr_5m_p98_20d"),
        rvol=_get("rvol"),
        gap_and_fade_flag=bool(_get("gap_and_fade_flag")) if _get("gap_and_fade_flag") is not None else False,
        vwap_cross_count_before_signal=int(_get("vwap_cross_count") or 0),
        spread_pct=spread_pct,
        spread_available=spread_available,
        has_open_position=has_open_position,
    )


# ---------------------------------------------------------------------------
# Duck-typed strategy wrapper (for factory registration / selection by name)
# ---------------------------------------------------------------------------


EDGE_HYPOTHESIS = (
    "Liquid mega-cap names occasionally open with abnormal volume while the "
    "index (SPY/QQQ) is directionally aligned. On those days, institutional "
    "VWAP/POV-style execution can create persistent one-directional order "
    "flow for 1-3 hours. Raw opening-range breakout entries buy at maximum "
    "short-term extension and are exposed to breakout-fade algos selling "
    "into that same candle; many fake breakouts die within 2-5 candles. "
    "Requiring a held pullback after a confirmed breakout, and only entering "
    "on a break of the pullback bar's high, avoids most fakeouts, gives a "
    "better price location, and gives a more meaningful stop below the "
    "pullback low. RVOL + gap filters select catalyst-like days; SPY/QQQ "
    "VWAP alignment avoids single-stock strength being absorbed by "
    "index-level selling. Stacked edge: catalyst-day selection (RVOL) x "
    "directional confirmation (ORB) x market alignment (SPY/QQQ VWAP) x "
    "superior pullback entry x structural stop below the pullback low."
)

FIDELITY_CHECKLIST = {
    "no_breakout_candle_entry": (
        True,
        "generate_signal() only returns a Signal from ARMED_TRIGGER, reached "
        "only after a held pullback; the breakout bar itself only moves the "
        "state from WAIT_BREAKOUT to WAIT_PULLBACK and can never fire a trade.",
    ),
    "fifteen_minute_opening_range": (
        True,
        "features/intraday_indicators.compute_opening_range() uses the "
        "09:30:00-09:44:59 ET window (opening_range_minutes=15 by default).",
    ),
    "pullback_state_machine": (
        True,
        "WAIT_BREAKOUT -> WAIT_PULLBACK -> ARMED_TRIGGER implemented in "
        "generate_signal() with re-arm (max 2) and retry (max 1) limits.",
    ),
    "time_of_day_matched_rvol": (
        True,
        "features/intraday_indicators.add_time_of_day_rvol() divides today's "
        "cumulative volume by the trailing-20-session average cumulative "
        "volume at the SAME clock time, not a naive full-day average.",
    ),
    "spy_qqq_vwap_agreement": (
        True,
        "check_market_filter() requires both SPY and QQQ closed 5m bars "
        "above their own session VWAP; disagreement structurally fails both "
        "checks simultaneously.",
    ),
    "or_width_sanity_filter": (
        True,
        "check_market_filter() requires 0.15*ATR_D <= OR width <= 1.0*ATR_D.",
    ),
    "gap_and_fade_blacklist": (
        True,
        "features/intraday_indicators.add_gap_and_fade_flag() flags sessions "
        "with gap > 1*ATR_D closing in the bottom third of the first "
        "15-minute bar and below the open; check_market_filter() rejects them.",
    ),
    "vwap_cross_chop_filter": (
        True,
        "features/intraday_indicators.add_vwap_cross_count() counts VWAP "
        "crosses per session; check_market_filter() rejects > 4 crosses.",
    ),
    "daily_atr_percent_filter": (
        True,
        "check_market_filter() rejects stock ATR_D_pct < 0.015.",
    ),
    "five_minute_atr_percentile_chaos_filter": (
        True,
        "features/intraday_indicators.add_atr5m_percentile_threshold() "
        "computes a trailing-20-session 98th percentile of 5m ATR; "
        "check_market_filter() rejects bars above that threshold.",
    ),
    "stop_distance_cap": (
        True,
        "calculate_stop() returns None (skip trade) when entry-stop distance "
        "exceeds 1.5*ATR_5m.",
    ),
    "scale_out_at_1r": (
        True,
        "should_exit() returns SCALE_HALF at +1.0R and marks position.scaled.",
    ),
    "breakeven_after_scale": (
        True,
        "should_exit() moves position.stop to entry + 0.1R at the same time "
        "it scales out at +1.0R.",
    ),
    "runner_trail": (
        True,
        "should_exit() applies a chandelier stop (highest_high - 2.2*ATR_5m) "
        "and a 5m close-below-EMA9 exit once the position has scaled.",
    ),
    "eod_flatten": (
        True,
        "should_exit() forces EOD_FLATTEN at/after 15:50 ET regardless of "
        "any other condition.",
    ),
    "long_only": (
        True,
        "There is no short/SELL-first code path anywhere in generate_signal() "
        "or Signal; side is hardcoded to 'LONG'.",
    ),
    "spread_filter": (
        "conditional",
        "spread_pct is honored when SymbolSnapshot.spread_available=True. "
        "Historical 1-minute OHLCV bars in this repo do not include "
        "bid/ask, so the backtest engine marks spread as UNAVAILABLE and "
        "reports it explicitly rather than fabricating a spread.",
    ),
    "fomc_calendar_filter": (
        False,
        "No economic calendar exists in this repo. The strategy's own 11:15 "
        "ET entry cutoff makes a 13:30-14:00 FOMC block moot for v1.0, but "
        "no calendar-driven check was implemented. Documented as a TODO.",
    ),
}


class OrbPullbackContinuationStrategy:
    """Duck-typed factory-registration wrapper for ORB-PBC v1.0.

    The generic ``backtesting/profitability_replay.run_profitability_replay``
    engine only supports single, full-size, full-exit positions per symbol.
    ORB-PBC requires per-symbol/per-day state (breakout/pullback/trigger
    phases, re-arm counters), partial scale-outs at +1R, breakeven stop
    moves, and chandelier trailing exits -- none of which the generic engine
    can express. Running ORB-PBC through the generic engine would therefore
    silently produce a fidelity-degraded (and misleading) backtest.

    To avoid that failure mode, this wrapper is intentionally inert when
    called through the generic per-bar ``evaluate_entry``/``evaluate_exit``
    interface: it always rejects entries with a clear reason. Real ORB-PBC
    backtests must go through ``backtesting/orb_pbc_engine.py`` (via
    ``orb_pbc_runner.py``), which uses the exact same state-machine functions
    (``generate_signal``, ``calculate_stop``, ``should_exit``,
    ``risk_gate_check``) defined in this module.

    Registering this class in ``strategies/factory.py`` still satisfies
    "the strategy can be selected by name" -- ``get_strategy(...)`` resolves
    it -- without ever producing fabricated or degraded performance numbers.
    """

    name = config.ORB_PBC_STRATEGY_NAME
    research_only = True
    side = "long_only"
    uses_session_features = False

    UNIVERSE = set(config.ORB_PBC_SYMBOLS)

    def entry_window_times(self) -> tuple[str, str]:
        return config.ORB_PBC_SIGNAL_WINDOW_START, config.ORB_PBC_SIGNAL_WINDOW_END

    def force_close_time(self) -> str:
        return config.ORB_PBC_EOD_FLATTEN_TIME

    def max_positions(self) -> int:
        return int(config.ORB_PBC_MAX_CONCURRENT_POSITIONS)

    def max_trades_per_day(self) -> int:
        return int(config.ORB_PBC_MAX_TRADES_PER_DAY)

    def max_losing_trades_per_day(self) -> int:
        return int(config.ORB_PBC_CONSECUTIVE_FULL_STOP_LOSSES_LIMIT)

    def holds_overnight(self) -> bool:
        return False

    def evaluate_entry(self, symbol: str, features: dict, regime: dict) -> tuple[bool, dict]:
        return False, {
            "entry_approved": False,
            "rejection_reason": (
                "orb_pullback_continuation_v1 requires the dedicated ORB-PBC "
                "engine (run via orb_pbc_runner.py) for state-machine and "
                "scale-out fidelity; it intentionally never trades through "
                "the generic per-bar replay engine."
            ),
            "strategy_name": self.name,
        }

    def evaluate_exit(self, position, features, regime, holding_minutes, in_open_window=False) -> tuple[bool, str]:
        return False, "hold"


# ---------------------------------------------------------------------------
# NOTE on v1.1 short concept (documented, NOT implemented):
#
# A future short-side variant could mirror the long pullback-continuation
# structure on breakdowns below the opening range low, but:
#   - the current universe (NVDA/META/AMD/TSLA) has structural upward drift
#     and strong dip-buying behavior, so short-side continuation setups
#     likely need materially different pullback/target parameters;
#   - mirroring the long-side parameters onto shorts would double the
#     parameter surface tested against the same (already limited) sample
#     of trading days, which risks overfitting rather than proving an edge;
#   - the long side must be proven first, in isolation, before adding a
#     second side that competes for the same max-concurrent-positions and
#     max-trades-per-day budget.
# ---------------------------------------------------------------------------
