"""Dedicated backtest engine for ORB-PBC v1.0.

RESEARCH ONLY -- this module never places real orders and never touches
``config.TRADING_MODE`` or any live-trading flag.

Why a dedicated engine (instead of the generic
``backtesting/profitability_replay.run_profitability_replay``)?

The generic engine models each strategy as a stateless per-bar function that
returns a single full-size entry and a single full-size exit. ORB-PBC needs:

  * per-symbol/per-day state (WAIT_BREAKOUT -> WAIT_PULLBACK -> ARMED_TRIGGER,
    with re-arm/retry counters) that persists across bars,
  * a partial scale-out at +1R, a breakeven stop move, and a chandelier
    trailing stop on the runner -- i.e. TWO exit legs per entry, and
  * a correlation cap (never hold NVDA and AMD at once) and a
    losing-streak/losing-day risk-halving rule layered on top of the shared
    ``risk.risk_gate.RiskGate``.

None of that is expressible through the generic engine's duck-typed
``evaluate_entry``/``evaluate_exit`` interface without silently degrading
fidelity, so ``strategies/orb_pullback_continuation.py`` refuses to trade
through that path (see its module docstring). This engine reuses the exact
same pure state-machine functions from that module for every trading
decision, and reuses ``risk.risk_gate.RiskGate`` for the shared safety gates
(kill switch, trading-mode gate, daily loss, max drawdown, max trades/day,
max concurrent positions) -- it adds ORB-PBC-specific checks on top, it does
not bypass them.

Execution/realism notes (documented, not hidden):

  * Signals are evaluated on completed 5-minute bars, per the spec's
    "signals are evaluated on 5-minute bars" instruction.
  * Stop-loss checks use the completed bar's LOW (worst case within the bar)
    so a real intrabar stop touch is not hidden by a bar that recovers by
    its close. Scale-out-at-+1R checks use the bar's HIGH (best case), since
    a resting limit order could fill anywhere in the bar. All other exits
    (failed breakout, market-filter failure, time stop, EMA/chandelier
    trail) use the bar's CLOSE, per the letter of the spec.
  * Bid/ask spread data does not exist in this repo's historical 1-minute
    OHLCV CSVs. The spread filter is therefore marked UNAVAILABLE throughout
    (``spread_available=False``) rather than fabricated, per the spec's
    explicit instruction to do so when spread data is missing.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import time as dt_time
from typing import Optional

import pandas as pd
from zoneinfo import ZoneInfo

import config
from backtesting.profitability_replay import load_symbol_data
from features.intraday_indicators import build_orb_pbc_feature_frame
from risk.risk_gate import RiskGate
from strategies.orb_pullback_continuation import (
    DEFAULT_CONFIG,
    DailyBook,
    OrbPbcConfig,
    OrbPullbackContinuationStrategy,
    Position,
    SymbolDayState,
    bar_from_row,
    calculate_position_size,
    calculate_stop,
    generate_signal,
    risk_gate_check,
    should_exit,
    snapshot_from_row,
)

EASTERN = ZoneInfo("America/New_York")


@dataclass
class EngineResult:
    trade_rows: list
    equity_curve: list
    diagnostics: dict
    starting_equity: float
    ending_equity: float
    data_notes: list = field(default_factory=list)


def run_orb_pbc_backtest(
    symbols: list[str],
    market_filter_symbols: list[str] = None,
    data_dir: str = "historical_data",
    start_date: str = None,
    end_date: str = None,
    starting_equity: float = None,
    cfg: OrbPbcConfig = DEFAULT_CONFIG,
    include_costs: bool = True,
    slippage_multiplier: float = 1.0,
    correlated_pairs=None,
) -> EngineResult:
    market_filter_symbols = market_filter_symbols or list(config.ORB_PBC_MARKET_FILTER_SYMBOLS)
    starting_equity = float(starting_equity if starting_equity is not None else config.ORB_PBC_EQUITY)
    correlated_pairs = correlated_pairs if correlated_pairs is not None else config.ORB_PBC_CORRELATED_PAIRS

    all_symbols = list(dict.fromkeys(list(symbols) + list(market_filter_symbols)))
    raw_1m = load_symbol_data(all_symbols, data_dir, start_date, end_date)

    data_notes = []
    for symbol in all_symbols:
        if symbol not in raw_1m or raw_1m[symbol].empty:
            data_notes.append(f"No 1-minute data available for {symbol} in the requested window.")

    feature_frames = {}
    for symbol in all_symbols:
        if symbol in raw_1m and not raw_1m[symbol].empty:
            frame = build_orb_pbc_feature_frame(
                raw_1m[symbol],
                opening_range_minutes=cfg.opening_range_minutes,
                rvol_lookback_days=config.ORB_PBC_RVOL_LOOKBACK_DAYS,
                atr5m_lookback_days=config.ORB_PBC_ATR5M_LOOKBACK_DAYS,
            )
            if not frame.empty:
                feature_frames[symbol] = frame.set_index("timestamp").sort_index()

    trade_symbols = [symbol for symbol in symbols if symbol in feature_frames]
    missing_trade_symbols = [symbol for symbol in symbols if symbol not in feature_frames]
    for symbol in missing_trade_symbols:
        data_notes.append(f"{symbol} excluded from this run: no usable feature data.")

    if any(symbol not in feature_frames for symbol in market_filter_symbols):
        missing = [s for s in market_filter_symbols if s not in feature_frames]
        data_notes.append(
            f"Market filter symbol(s) {missing} missing data; no trades can be evaluated "
            "without SPY/QQQ regime data (fail-safe: no trade)."
        )
        return EngineResult(
            trade_rows=[],
            equity_curve=[],
            diagnostics={"reason": "missing market filter data"},
            starting_equity=starting_equity,
            ending_equity=starting_equity,
            data_notes=data_notes,
        )

    if not trade_symbols:
        data_notes.append("No trade symbols had usable data; returning empty result.")
        return EngineResult(
            trade_rows=[],
            equity_curve=[],
            diagnostics={"reason": "no trade symbols with data"},
            starting_equity=starting_equity,
            ending_equity=starting_equity,
            data_notes=data_notes,
        )

    all_timestamps = sorted(
        set().union(*[set(feature_frames[s].index) for s in trade_symbols])
    )
    session_dates = sorted({ts.tz_convert(EASTERN).date() for ts in all_timestamps})

    risk_shim = OrbPullbackContinuationStrategy()
    risk_gate = RiskGate(starting_equity, strategy=risk_shim)

    equity = starting_equity
    peak_equity = starting_equity
    consecutive_losing_days = 0
    base_risk_pct = cfg.risk_per_trade_pct
    current_risk_pct = base_risk_pct

    trade_rows = []
    equity_curve = []
    diagnostics = Counter()
    trade_id_counter = 0

    for session_date in session_dates:
        risk_gate.update_equity(equity)
        book = DailyBook(start_equity=equity)
        day_states = {symbol: SymbolDayState() for symbol in trade_symbols}
        open_positions: dict[str, dict] = {}

        day_timestamps = [ts for ts in all_timestamps if ts.tz_convert(EASTERN).date() == session_date]
        day_timestamps.sort()

        for timestamp in day_timestamps:
            now_et = timestamp.tz_convert(EASTERN)
            spy_row = _row_asof(feature_frames.get(market_filter_symbols[0]), timestamp)
            qqq_row = (
                _row_asof(feature_frames.get(market_filter_symbols[1]), timestamp)
                if len(market_filter_symbols) > 1
                else spy_row
            )
            if spy_row is None or qqq_row is None:
                continue
            spy_snapshot = snapshot_from_row(market_filter_symbols[0], spy_row, now=now_et)
            qqq_snapshot = snapshot_from_row(
                market_filter_symbols[1] if len(market_filter_symbols) > 1 else market_filter_symbols[0],
                qqq_row,
                now=now_et,
            )

            # 1) Manage existing open positions first.
            for symbol in list(open_positions.keys()):
                row = _row_asof(feature_frames.get(symbol), timestamp)
                if row is None:
                    continue
                trade_id_counter = _process_exits(
                    symbol,
                    row,
                    now_et,
                    open_positions,
                    book,
                    trade_rows,
                    risk_gate,
                    spy_snapshot,
                    qqq_snapshot,
                    cfg,
                    include_costs,
                    slippage_multiplier,
                    trade_id_counter,
                    diagnostics,
                )
            equity = starting_equity + sum(row["pnl_dollars"] for row in trade_rows)

            # 2) Advance state machines / look for new entries.
            for symbol in trade_symbols:
                if symbol in open_positions:
                    continue
                row = _row_asof(feature_frames.get(symbol), timestamp)
                if row is None:
                    continue

                state = day_states[symbol]
                stock_snapshot = snapshot_from_row(
                    symbol,
                    row,
                    now=now_et,
                    has_open_position=symbol in open_positions,
                    spread_available=False,
                )
                signal = generate_signal(stock_snapshot, spy_snapshot, qqq_snapshot, state, now_et, cfg)
                if signal is None:
                    continue

                diagnostics["signals_generated"] += 1
                stop = calculate_stop(signal, stock_snapshot.atr_5m, cfg)
                if stop is None:
                    diagnostics["rejected_stop_distance"] += 1
                    continue

                allowed_supplementary, reason = risk_gate_check(
                    book, symbol, cfg, correlated_pairs=correlated_pairs
                )
                if not allowed_supplementary:
                    diagnostics[f"rejected_risk_{reason}"] += 1
                    continue

                allowed_shared, shared_reason = risk_gate.can_trade(
                    now_et.astimezone(ZoneInfo("UTC")) if now_et.tzinfo else now_et,
                    equity,
                    book.realized_pnl,
                    open_positions,
                )
                if not allowed_shared:
                    diagnostics[f"rejected_shared_risk_gate_{shared_reason}"] += 1
                    continue

                shares = calculate_position_size(equity, signal.entry, stop, current_risk_pct, cfg)
                if shares < 1:
                    diagnostics["rejected_size_too_small"] += 1
                    continue

                notional = shares * signal.entry
                max_notional = min(
                    equity * float(config.ORB_PBC_MAX_NOTIONAL_EQUITY_MULTIPLE),
                    equity * float(config.ORB_PBC_MAX_BUYING_POWER_UTILIZATION) * 4,
                )
                if notional > max_notional:
                    shares = int(max_notional // signal.entry)
                if shares < 1:
                    diagnostics["rejected_notional_cap"] += 1
                    continue

                fill_price = signal.entry
                if include_costs:
                    fill_price += _slippage_per_share(symbol, slippage_multiplier)

                position = Position(
                    symbol=symbol,
                    entry_price=fill_price,
                    initial_stop=stop,
                    stop=stop,
                    shares=shares,
                    entry_time=now_et,
                )
                open_positions[symbol] = {
                    "position": position,
                    "legs": [],
                    "trade_id": trade_id_counter,
                    "rvol_at_entry": stock_snapshot.rvol,
                }
                trade_id_counter += 1
                book.trade_count += 1
                book.open_positions[symbol] = position
                state.entries_today += 1
                risk_gate.record_open_trade(now_et.astimezone(ZoneInfo("UTC")) if now_et.tzinfo else now_et)
                diagnostics["entries_opened"] += 1

        # Safety-net EOD flatten (should already be handled by should_exit, but
        # guarantees no overnight holds even if the timeline ends early).
        for symbol in list(open_positions.keys()):
            row = _row_asof(feature_frames.get(symbol), day_timestamps[-1]) if day_timestamps else None
            if row is None:
                continue
            entry = open_positions[symbol]
            position: Position = entry["position"]
            fill_price = float(row["close"])
            trade_id_counter = _finalize_position(
                symbol,
                position,
                entry,
                fill_price,
                row["timestamp"],
                "EOD_FLATTEN_SAFETY_NET",
                open_positions,
                book,
                trade_rows,
                risk_gate,
                include_costs,
                slippage_multiplier,
                trade_id_counter,
                is_stop=False,
            )
            diagnostics["eod_safety_net_flattens"] += 1

        for symbol, state in day_states.items():
            diagnostics["breakout_confirmations"] += state.breakout_confirmations
            diagnostics["pullbacks_validated"] += state.pullbacks_validated
            diagnostics["state_machine_triggers_fired"] += state.triggers_fired
            diagnostics["state_machine_invalidations"] += state.invalidations

        equity = starting_equity + sum(row["pnl_dollars"] for row in trade_rows)
        peak_equity = max(peak_equity, equity)
        day_pnl = equity - book.start_equity
        if day_pnl > 0:
            consecutive_losing_days = 0
            current_risk_pct = base_risk_pct
        elif day_pnl < 0:
            consecutive_losing_days += 1
            if consecutive_losing_days >= int(config.ORB_PBC_RISK_HALVING_AFTER_LOSING_DAYS):
                current_risk_pct = base_risk_pct * float(config.ORB_PBC_RISK_HALVING_FACTOR)

        equity_curve.append(
            {
                "timestamp": day_timestamps[-1] if day_timestamps else pd.Timestamp(session_date, tz="UTC"),
                "equity": equity,
                "session_date": str(session_date),
            }
        )

    return EngineResult(
        trade_rows=trade_rows,
        equity_curve=equity_curve,
        diagnostics=dict(diagnostics),
        starting_equity=starting_equity,
        ending_equity=equity,
        data_notes=data_notes,
    )


def _row_asof(frame: Optional[pd.DataFrame], timestamp):
    if frame is None or frame.empty:
        return None
    try:
        position = frame.index.searchsorted(timestamp, side="right") - 1
    except TypeError:
        return None
    if position < 0:
        return None
    row = frame.iloc[position].copy()
    row["timestamp"] = frame.index[position]
    return row


def _slippage_per_share(symbol: str, multiplier: float) -> float:
    base = (
        config.ORB_PBC_TSLA_SLIPPAGE_PER_SHARE
        if symbol == "TSLA"
        else config.ORB_PBC_DEFAULT_SLIPPAGE_PER_SHARE
    )
    return base * multiplier


def _commission(shares: int) -> float:
    return abs(shares) * config.ORB_PBC_COMMISSION_PER_SHARE


def _process_exits(
    symbol,
    row,
    now_et,
    open_positions,
    book,
    trade_rows,
    risk_gate,
    spy_snapshot,
    qqq_snapshot,
    cfg,
    include_costs,
    slippage_multiplier,
    trade_id_counter,
    diagnostics,
):
    entry = open_positions[symbol]
    position: Position = entry["position"]
    bar = bar_from_row(row)

    now_time = now_et.time()
    if now_time >= cfg.eod_flatten_time:
        trade_id_counter = _finalize_position(
            symbol, position, entry, bar.close, row["timestamp"], "EOD_FLATTEN",
            open_positions, book, trade_rows, risk_gate, include_costs, slippage_multiplier,
            trade_id_counter, is_stop=False,
        )
        diagnostics["exit_EOD_FLATTEN"] += 1
        return trade_id_counter

    low_snapshot = snapshot_from_row(symbol, row, now=now_et, current_price=bar.low, has_open_position=True)
    reason_low = should_exit(position, low_snapshot, spy_snapshot, qqq_snapshot, now_et, cfg)
    if reason_low == "STOP":
        fill_price = position.stop if bar.open >= position.stop else bar.open
        trade_id_counter = _finalize_position(
            symbol, position, entry, fill_price, row["timestamp"], "STOP",
            open_positions, book, trade_rows, risk_gate, include_costs, slippage_multiplier,
            trade_id_counter, is_stop=True,
        )
        diagnostics["exit_STOP"] += 1
        return trade_id_counter

    high_snapshot = snapshot_from_row(symbol, row, now=now_et, current_price=bar.high, has_open_position=True)
    reason_high = should_exit(position, high_snapshot, spy_snapshot, qqq_snapshot, now_et, cfg)
    if reason_high == "SCALE_HALF":
        scale_fill = position.entry_price + cfg.scale_out_at_r * position.risk_per_share
        _apply_scale_out(symbol, position, entry, scale_fill, row["timestamp"], book, include_costs, slippage_multiplier)
        diagnostics["exit_SCALE_HALF"] += 1
        return trade_id_counter

    close_snapshot = snapshot_from_row(symbol, row, now=now_et, current_price=bar.close, has_open_position=True)
    reason_close = should_exit(position, close_snapshot, spy_snapshot, qqq_snapshot, now_et, cfg)
    if reason_close in ("FAILED_BREAKOUT", "MARKET_FILTER_FAIL", "TIME_STOP", "TRAIL_EMA"):
        trade_id_counter = _finalize_position(
            symbol, position, entry, bar.close, row["timestamp"], reason_close,
            open_positions, book, trade_rows, risk_gate, include_costs, slippage_multiplier,
            trade_id_counter, is_stop=False,
        )
        diagnostics[f"exit_{reason_close}"] += 1
        return trade_id_counter

    if reason_close == "STOP":
        # Chandelier trail (mutated onto position.stop inside should_exit) can
        # tighten the stop above the bar's close; catch that case here too.
        fill_price = position.stop if bar.open >= position.stop else bar.open
        trade_id_counter = _finalize_position(
            symbol, position, entry, fill_price, row["timestamp"], "TRAIL_STOP",
            open_positions, book, trade_rows, risk_gate, include_costs, slippage_multiplier,
            trade_id_counter, is_stop=True,
        )
        diagnostics["exit_TRAIL_STOP"] += 1

    return trade_id_counter


def _apply_scale_out(symbol, position: Position, entry, fill_price, timestamp, book, include_costs, slippage_multiplier):
    scale_shares = int(round(position.shares * config.ORB_PBC_SCALE_OUT_FRACTION))
    scale_shares = max(1, min(scale_shares, position.remaining_shares))

    exit_price = fill_price
    if include_costs:
        exit_price -= _slippage_per_share(symbol, slippage_multiplier)

    gross = (exit_price - position.entry_price) * scale_shares
    costs = _commission(scale_shares) if include_costs else 0.0
    entry["legs"].append(
        {
            "shares": scale_shares,
            "exit_price": exit_price,
            "exit_timestamp": timestamp,
            "reason": "SCALE_HALF",
            "pnl_dollars": gross - costs,
        }
    )
    position.remaining_shares -= scale_shares


def _finalize_position(
    symbol,
    position: Position,
    entry,
    fill_price,
    timestamp,
    reason,
    open_positions,
    book,
    trade_rows,
    risk_gate,
    include_costs,
    slippage_multiplier,
    trade_id_counter,
    is_stop: bool,
):
    remaining = getattr(position, "remaining_shares", position.shares)
    exit_price = fill_price
    if include_costs:
        exit_price -= _slippage_per_share(symbol, slippage_multiplier)

    gross = (exit_price - position.entry_price) * remaining
    costs = _commission(remaining) if include_costs else 0.0
    entry["legs"].append(
        {
            "shares": remaining,
            "exit_price": exit_price,
            "exit_timestamp": timestamp,
            "reason": reason,
            "pnl_dollars": gross - costs,
        }
    )

    legs = entry["legs"]
    total_shares = sum(leg["shares"] for leg in legs)
    total_pnl = sum(leg["pnl_dollars"] for leg in legs)
    total_proceeds = sum(leg["shares"] * leg["exit_price"] for leg in legs)
    blended_exit_price = total_proceeds / total_shares if total_shares else fill_price
    was_scaled = any(leg["reason"] == "SCALE_HALF" for leg in legs)
    full_stop_loss = is_stop and not was_scaled and total_pnl < 0

    trade_rows.append(
        {
            "ticker": symbol,
            "entry_timestamp": position.entry_time,
            "exit_timestamp": timestamp,
            "entry_price": position.entry_price,
            "exit_price": blended_exit_price,
            "position_size": total_shares,
            "stop_loss": position.initial_stop,
            "take_profit": None,
            "pnl_dollars": total_pnl,
            "pnl_percent": (blended_exit_price - position.entry_price) / position.entry_price
            if position.entry_price
            else None,
            "win_loss": "WIN" if total_pnl > 0 else "LOSS",
            "hold_time_minutes": (timestamp - position.entry_time).total_seconds() / 60.0
            if hasattr(timestamp - position.entry_time, "total_seconds")
            else None,
            "strategy_name": config.ORB_PBC_STRATEGY_NAME,
            "setup_type": "orb_pullback_continuation",
            "rsi": None,
            "rvol": entry.get("rvol_at_entry"),
            "exit_reason": reason,
            "scaled": was_scaled,
            "r_multiple": total_pnl / (position.risk_per_share * total_shares)
            if position.risk_per_share and total_shares
            else None,
            "trade_id": entry["trade_id"],
        }
    )

    risk_gate.record_closed_trade(
        timestamp.to_pydatetime() if hasattr(timestamp, "to_pydatetime") else timestamp, total_pnl
    )
    book.realized_pnl += total_pnl
    if full_stop_loss:
        book.consecutive_full_stop_losses += 1
    elif total_pnl > 0:
        book.consecutive_full_stop_losses = 0

    book.open_positions.pop(symbol, None)
    open_positions.pop(symbol, None)
    return trade_id_counter
