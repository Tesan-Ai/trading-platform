from datetime import time
from typing import Dict, List
import os

import pandas as pd
from zoneinfo import ZoneInfo

import config
from analytics.trade_analytics import build_trade_rows, calculate_report
from features.daily_context import build_daily_regime_map, daily_regime_for_date
from features.feature_store import add_feature_columns, latest_features
from features.session_features import add_session_feature_columns
from regime.market_regime import classify_market_regime
from risk.risk_gate import RiskGate
from signal_logger import log_signal
from strategies.factory import get_strategy

EASTERN = ZoneInfo("America/New_York")


class ProfitabilityPortfolio:
    def __init__(self, starting_cash: float):
        self.cash = float(starting_cash)
        self.positions = {}
        self.trade_log = []
        self.equity_curve = []
        self.starting_cash = float(starting_cash)

    def total_position_value(self, current_prices: Dict[str, float]) -> float:
        total = 0.0
        for symbol, position in self.positions.items():
            if symbol in current_prices:
                total += int(position["shares"]) * float(current_prices[symbol])
        return total

    def equity(self, current_prices: Dict[str, float]) -> float:
        return self.cash + self.total_position_value(current_prices)

    def buy(self, timestamp, symbol: str, shares: int, fill_price: float, entry_details: dict, features: dict, regime: dict) -> None:
        cost = shares * fill_price
        if shares <= 0 or cost > self.cash:
            return

        self.cash -= cost
        position = {
            "symbol": symbol,
            "shares": shares,
            "entry_price": fill_price,
            "entry_timestamp": timestamp,
            "stop_loss": entry_details["stop_loss"],
            "take_profit": entry_details["take_profit"],
            "risk_per_share": entry_details.get(
                "risk_per_share", fill_price - entry_details["stop_loss"]
            ),
            "selected_stop_method": entry_details.get("selected_stop_method"),
            "strategy_name": entry_details["strategy_name"],
            "setup_type": entry_details["setup_type"],
            "reason": entry_details["reason"]
        }
        self.positions[symbol] = position

        self.trade_log.append({
            "timestamp": timestamp,
            "action": "BUY",
            "symbol": symbol,
            "price": fill_price,
            "shares": shares,
            "stop_loss": entry_details["stop_loss"],
            "take_profit": entry_details["take_profit"],
            "risk_per_share": position["risk_per_share"],
            "selected_stop_method": position.get("selected_stop_method"),
            "strategy_name": entry_details["strategy_name"],
            "setup_type": entry_details["setup_type"],
            "reason": entry_details["reason"],
            "rsi_7": features.get("rsi_7"),
            "rsi_14": features.get("rsi_14"),
            "relative_volume": features.get("relative_volume"),
            "atr_14": features.get("atr_14"),
            "atr_percent": features.get("atr_percent"),
            "ema_trend": _ema_trend_label(features),
            "vwap_distance": features.get("vwap_distance"),
            "distance_from_vwap_atr": features.get("distance_from_vwap_atr"),
            "opening_range_high": features.get("opening_range_high"),
            "opening_range_low": features.get("opening_range_low"),
            "opening_range_midpoint": features.get("opening_range_midpoint"),
            "market_regime": regime.get("regime"),
            "sector": features.get("sector", "UNKNOWN"),
            "spread_percent": features.get("spread_percent"),
            "volume": features.get("volume"),
            "macd_slope": features.get("macd_slope"),
            "breakout_distance": features.get("breakout_distance"),
            "spy_above_vwap_at_entry": entry_details.get("spy_above_vwap"),
            "qqq_above_vwap_at_entry": entry_details.get("qqq_above_vwap"),
        })

    def sell(self, timestamp, symbol: str, fill_price: float, reason: str) -> float:
        if symbol not in self.positions:
            return 0.0

        position = self.positions.pop(symbol)
        shares = int(position["shares"])
        proceeds = shares * fill_price
        self.cash += proceeds
        pnl_dollars = (fill_price - float(position["entry_price"])) * shares

        self.trade_log.append({
            "timestamp": timestamp,
            "action": "SELL",
            "symbol": symbol,
            "price": fill_price,
            "shares": shares,
            "reason": reason,
            "entry_price": position["entry_price"],
            "pnl_percent": (fill_price - float(position["entry_price"])) / float(position["entry_price"])
        })
        return pnl_dollars


def load_symbol_data(
    symbols: List[str],
    data_dir: str,
    start_date: str | None = None,
    end_date: str | None = None,
) -> Dict[str, pd.DataFrame]:
    loaded = {}
    for symbol in symbols:
        file_path = os.path.join(data_dir, f"{symbol}.csv")
        if not os.path.exists(file_path):
            continue

        data_frame = pd.read_csv(file_path)
        data_frame["timestamp"] = pd.to_datetime(data_frame["timestamp"], utc=True)
        data_frame = data_frame.sort_values("timestamp").reset_index(drop=True)
        data_frame = _filter_date_window(data_frame, start_date, end_date)
        data_frame = _regular_market_hours_only(data_frame)
        loaded[symbol] = data_frame
    return loaded


def build_timeline(symbol_data: Dict[str, pd.DataFrame]) -> List[pd.Timestamp]:
    timestamps = set()
    for data_frame in symbol_data.values():
        timestamps.update(data_frame["timestamp"].tolist())
    return sorted(timestamps)


def run_profitability_replay(
    symbols: List[str],
    data_dir: str = "historical_data",
    starting_cash: float = 100000.0,
    start_date: str | None = None,
    end_date: str | None = None,
    strategy=None,
) -> dict:
    symbol_data = load_symbol_data(symbols, data_dir, start_date, end_date)
    strategy = strategy or get_strategy()
    featured_symbol_data = {
        symbol: _prepare_feature_frame(data_frame, strategy)
        for symbol, data_frame in symbol_data.items()
    }
    featured_symbol_data = {
        symbol: data_frame.dropna().reset_index(drop=True)
        for symbol, data_frame in featured_symbol_data.items()
        if not data_frame.empty
    }
    timeline = build_timeline(featured_symbol_data)
    market_feature_frame = _build_market_feature_frame(symbol_data, strategy)
    market_filter_frames = _build_market_filter_frames(symbol_data, strategy)
    regime_source = symbol_data.get(config.MARKET_REGIME_SYMBOL)
    if regime_source is None or regime_source.empty:
        regime_source = _build_market_proxy_from_full_data(symbol_data)
    daily_regime_map = build_daily_regime_map(regime_source)
    portfolio = ProfitabilityPortfolio(starting_cash)
    risk_gate = RiskGate(starting_cash, strategy=strategy)
    entries_by_symbol_day = set()
    exit_checked_dates = set()
    signal_rows = []

    if not featured_symbol_data or not timeline:
        return {
            "portfolio": portfolio,
            "trade_rows": [],
            "report": {"closed_trades": 0},
            "latest_regime": {"regime": "UNKNOWN", "trade_allowed": False}
        }

    latest_regime = {"regime": "UNKNOWN", "trade_allowed": False, "reason": "not evaluated"}
    day_start_equity = starting_cash
    current_day = None

    for current_timestamp in timeline:
        trade_date = current_timestamp.to_pydatetime().astimezone(EASTERN).date()
        if current_day != trade_date:
            current_day = trade_date
            day_start_equity = portfolio.equity({})
            entries_by_symbol_day = {
                key for key in entries_by_symbol_day if key[1] != trade_date
            }
            exit_checked_dates = {
                key for key in exit_checked_dates if key != trade_date
            }

        current_prices = _current_prices(featured_symbol_data, current_timestamp)
        latest_regime = _resolve_regime(
            strategy,
            market_feature_frame,
            current_timestamp,
            daily_regime_map,
            trade_date,
            market_filter_frames,
        )
        current_equity = portfolio.equity(current_prices)
        risk_gate.update_equity(current_equity)
        day_pnl = current_equity - day_start_equity

        _process_exits(
            portfolio,
            strategy,
            featured_symbol_data,
            current_timestamp,
            latest_regime,
            current_prices,
            risk_gate,
            exit_checked_dates,
        )

        if _should_force_close(strategy, current_timestamp):
            for symbol in list(portfolio.positions.keys()):
                if symbol in current_prices:
                    fill_price = _sell_fill(current_prices[symbol])
                    pnl = portfolio.sell(current_timestamp.to_pydatetime(), symbol, fill_price, "end of day close")
                    risk_gate.record_closed_trade(current_timestamp.to_pydatetime(), pnl)
            _record_equity(portfolio, current_timestamp, current_prices)
            continue

        if not _is_entry_window_open(strategy, current_timestamp):
            _record_equity(portfolio, current_timestamp, current_prices)
            continue

        allowed, _reason = risk_gate.can_trade(
            current_timestamp.to_pydatetime(),
            current_equity,
            day_pnl,
            portfolio.positions
        )
        if not allowed:
            _record_equity(portfolio, current_timestamp, current_prices)
            continue

        candidates = _rank_candidates(
            featured_symbol_data,
            current_timestamp,
            strategy,
            latest_regime,
            signal_rows,
            portfolio.equity(current_prices),
        )
        for candidate in candidates:
            symbol = candidate["symbol"]
            if symbol in portfolio.positions:
                continue

            entry_key = (symbol, trade_date)
            if entry_key in entries_by_symbol_day:
                continue

            allowed, _reason = risk_gate.can_trade(
                current_timestamp.to_pydatetime(),
                portfolio.equity(current_prices),
                day_pnl,
                portfolio.positions
            )
            if not allowed:
                break

            shares = _position_size(
                portfolio.cash,
                current_equity,
                candidate["entry_details"]["entry_price"],
                candidate["entry_details"].get("risk_per_share"),
                strategy,
            )
            if shares <= 0:
                continue

            fill_price = _buy_fill(candidate["entry_details"]["entry_price"])
            portfolio.buy(
                current_timestamp.to_pydatetime(),
                symbol,
                shares,
                fill_price,
                candidate["entry_details"],
                candidate["features"],
                latest_regime
            )
            risk_gate.record_open_trade(current_timestamp.to_pydatetime())
            entries_by_symbol_day.add(entry_key)
            _log_signal_event(
                "ENTRY",
                candidate["entry_details"],
                shares=shares,
                account_equity=portfolio.equity(current_prices),
                signal_rows=signal_rows,
            )

        _record_equity(portfolio, current_timestamp, current_prices)

    trade_rows = build_trade_rows(portfolio.trade_log)
    report = calculate_report(trade_rows, portfolio.equity_curve)

    return {
        "portfolio": portfolio,
        "trade_rows": trade_rows,
        "report": report,
        "latest_regime": latest_regime,
        "signal_rows": signal_rows,
    }


def _process_exits(portfolio, strategy, featured_symbol_data, current_timestamp, regime, current_prices, risk_gate, exit_checked_dates=None) -> None:
    in_open_window = _is_entry_window_open(strategy, current_timestamp)
    trade_date = current_timestamp.to_pydatetime().astimezone(EASTERN).date()
    regime_exit_allowed = in_open_window

    if getattr(strategy, "name", "") == "daily_trend_v1":
        if exit_checked_dates is not None:
            if trade_date in exit_checked_dates or not in_open_window:
                regime_exit_allowed = False
            else:
                exit_checked_dates.add(trade_date)

    for symbol in list(portfolio.positions.keys()):
        if symbol not in current_prices:
            continue

        features = _features_at_or_before(symbol, featured_symbol_data[symbol], current_timestamp)

        if features is None:
            features = {"close": current_prices[symbol], "above_vwap": True}

        position = portfolio.positions[symbol]
        holding_minutes = (
            current_timestamp.to_pydatetime() - position["entry_timestamp"]
        ).total_seconds() / 60.0
        should_exit, reason = strategy.evaluate_exit(
            position,
            features,
            regime,
            holding_minutes,
            in_open_window=regime_exit_allowed,
        )

        if should_exit:
            fill_price = _sell_fill(current_prices[symbol])
            pnl = portfolio.sell(current_timestamp.to_pydatetime(), symbol, fill_price, reason)
            risk_gate.record_closed_trade(current_timestamp.to_pydatetime(), pnl)


def _rank_candidates(
    featured_symbol_data,
    current_timestamp,
    strategy,
    regime,
    signal_rows=None,
    account_equity=None,
) -> list[dict]:
    candidates = []

    for symbol, data_frame in featured_symbol_data.items():
        trade_symbols = getattr(config, "ORVWAP_TRADE_SYMBOLS", None)
        if getattr(strategy, "name", "") == config.ORVWAP_STRATEGY_NAME and trade_symbols and symbol not in trade_symbols:
            continue
        features = _features_at_or_before(symbol, data_frame, current_timestamp)
        if features is None:
            continue

        if hasattr(strategy, "build_signal_context"):
            details = strategy.build_signal_context(symbol, features, regime)
            passes = bool(details.get("entry_approved"))
        else:
            passes, details = strategy.evaluate_entry(symbol, features, regime)

        if hasattr(strategy, "build_signal_context"):
            _log_signal_event(
                "SIGNAL",
                details,
                account_equity=account_equity,
                signal_rows=signal_rows,
            )

        if not passes:
            continue

        if getattr(config, "ML_BRAIN_ENABLED", False):
            from ml_brain.integration import apply_ml_brain_filter, log_ml_prediction

            ml_allowed, details = apply_ml_brain_filter(details, features=features, regime=regime)
            log_ml_prediction(
                {
                    "ml_score": details.get("ml_score"),
                    "decision": details.get("ml_decision"),
                    "threshold": details.get("ml_threshold"),
                    "model_version": details.get("ml_model_version"),
                    "top_reasons": details.get("ml_top_reasons"),
                    "error": details.get("ml_error"),
                },
                details,
            )
            if hasattr(strategy, "build_signal_context"):
                _log_signal_event(
                    "ML_SIGNAL",
                    details,
                    account_equity=account_equity,
                    signal_rows=signal_rows,
                )
            if not ml_allowed:
                continue

        score = float(features.get("volume_ratio", features.get("relative_volume", 0.0)))
        if getattr(strategy, "name", "") == config.ORVWAP_STRATEGY_NAME:
            score = float(features.get("volume_ratio", 0.0))
        else:
            score = (
                float(features["relative_volume"])
                + max(0.0, float(features["breakout_distance"]) * 100)
                + max(0.0, float(features["macd_slope"]) * 100)
            )

        candidates.append({
            "symbol": symbol,
            "score": score,
            "features": features,
            "entry_details": details
        })

    candidates.sort(key=lambda item: item["score"], reverse=True)
    if getattr(config, "ACTIVE_STRATEGY", "") == "daily_trend_v1":
        symbol_rank = {symbol: index for index, symbol in enumerate(getattr(config, "TRADE_SYMBOLS", []))}
        candidates.sort(key=lambda item: symbol_rank.get(item["symbol"], 999))
    return candidates


def _current_prices(symbol_data, current_timestamp) -> dict:
    prices = {}
    for symbol, data_frame in symbol_data.items():
        row = _latest_row_at_or_before(data_frame, current_timestamp)
        if row is not None:
            prices[symbol] = float(row["close"])
    return prices


def _build_market_proxy_from_full_data(symbol_data):
    rows = []
    for data_frame in symbol_data.values():
        if not data_frame.empty:
            rows.append(data_frame[["timestamp", "open", "high", "low", "close", "volume"]].copy())

    if not rows:
        return pd.DataFrame()

    combined = pd.concat(rows)
    market_frame = combined.groupby("timestamp", as_index=False).agg({
        "open": "mean",
        "high": "mean",
        "low": "mean",
        "close": "mean",
        "volume": "sum"
    })
    return market_frame.sort_values("timestamp").reset_index(drop=True)


def _build_market_feature_frame(symbol_data, strategy=None):
    for market_symbol in ("SPY", "QQQ"):
        if market_symbol in symbol_data and not symbol_data[market_symbol].empty:
            return _prepare_feature_frame(symbol_data[market_symbol], strategy).dropna().reset_index(drop=True)

    return _prepare_feature_frame(
        _build_market_proxy_from_full_data(symbol_data),
        strategy,
    ).dropna().reset_index(drop=True)


def _build_market_filter_frames(symbol_data, strategy):
    if getattr(strategy, "name", "") != config.ORVWAP_STRATEGY_NAME:
        return {}

    frames = {}
    for symbol in (config.ORVWAP_MARKET_FILTER_SYMBOL, config.ORVWAP_TECH_FILTER_SYMBOL):
        if symbol in symbol_data and not symbol_data[symbol].empty:
            frames[symbol] = _prepare_feature_frame(symbol_data[symbol], strategy).dropna().reset_index(drop=True)
    return frames


def _prepare_feature_frame(data_frame, strategy):
    if getattr(strategy, "uses_session_features", False):
        entry_start = _parse_time(config.ORVWAP_ENTRY_START)
        entry_end = _parse_time(config.ORVWAP_ENTRY_END)
        return add_session_feature_columns(
            data_frame,
            entry_start=entry_start,
            entry_end=entry_end,
        )
    return add_feature_columns(data_frame)


def _latest_row_at_or_before(data_frame, current_timestamp):
    if data_frame.empty:
        return None

    timestamp_values = data_frame["timestamp"]
    matches = timestamp_values.searchsorted(current_timestamp, side="right") - 1

    if matches < 0:
        return None

    return data_frame.iloc[matches]


def _features_at_or_before(symbol, data_frame, current_timestamp):
    row = _latest_row_at_or_before(data_frame, current_timestamp)

    if row is None:
        return None

    features = row.to_dict()
    features["symbol"] = symbol
    return features


def _classify_market_regime_from_row(row):
    if row is None:
        return {
            "regime": "CHOP",
            "trade_allowed": False,
            "reason": "missing market features"
        }

    close = float(row["close"])
    ema_20 = float(row["ema_20"])
    ema_50 = float(row["ema_50"])
    ema_200 = float(row["ema_200"])
    ema_20_slope = float(row["ema_20_slope"])
    atr_percent = float(row["atr_percent"])
    relative_volume = float(row["relative_volume"])

    if relative_volume < 0.30:
        return {
            "regime": "LOW_LIQUIDITY",
            "trade_allowed": False,
            "reason": "market liquidity too low"
        }

    if atr_percent > 0.025:
        return {
            "regime": "HIGH_VOLATILITY",
            "trade_allowed": False,
            "reason": "market volatility expanded"
        }

    if close < ema_50 and ema_20 < ema_50 and ema_20_slope < 0:
        return {
            "regime": "RISK_OFF",
            "trade_allowed": False,
            "reason": "market risk off"
        }

    if close > ema_20 > ema_50 > ema_200 and ema_20_slope > 0:
        return {
            "regime": "BULL_TREND",
            "trade_allowed": True,
            "reason": "bull trend"
        }

    if close < ema_20 < ema_50 and ema_20_slope < 0:
        return {
            "regime": "BEAR_TREND",
            "trade_allowed": False,
            "reason": "bear trend"
        }

    return {
        "regime": "CHOP",
        "trade_allowed": False,
        "reason": "market is choppy"
    }


def _position_size(cash: float, equity: float, price: float, risk_per_share: float | None, strategy) -> int:
    if getattr(strategy, "name", "") == config.ORVWAP_STRATEGY_NAME and risk_per_share and risk_per_share > 0:
        risk_dollars = equity * float(config.ORVWAP_RISK_PER_TRADE_PCT)
        shares = int(risk_dollars // risk_per_share)
        max_dollars = min(
            cash * float(config.MAX_CAPITAL_PER_TRADE),
            cash * float(config.MAX_PORTFOLIO_EXPOSURE),
        )
        max_shares = int(max_dollars // price) if price > 0 else 0
        shares = min(shares, max_shares)
        if shares * price < float(config.MIN_TRADE_DOLLARS):
            return 0
        return shares

    trade_dollars = min(
        cash * float(config.MAX_CAPITAL_PER_TRADE),
        cash * float(config.MAX_PORTFOLIO_EXPOSURE)
    )
    if trade_dollars < float(config.MIN_TRADE_DOLLARS) or price <= 0:
        return 0
    return int(trade_dollars // price)


def _buy_fill(price: float) -> float:
    return float(price) * (1 + float(config.BACKTEST_SLIPPAGE_PERCENT))


def _sell_fill(price: float) -> float:
    return float(price) * (1 - float(config.BACKTEST_SLIPPAGE_PERCENT))


def _record_equity(portfolio, current_timestamp, current_prices) -> None:
    portfolio.equity_curve.append({
        "timestamp": current_timestamp,
        "equity": portfolio.equity(current_prices),
        "cash": portfolio.cash,
        "positions": len(portfolio.positions)
    })


def _is_buy_window_open(current_timestamp) -> bool:
    eastern_time = current_timestamp.to_pydatetime().astimezone(EASTERN).time()
    return _parse_time(config.BUY_START_TIME) <= eastern_time <= _parse_time(config.BUY_END_TIME)


def _resolve_regime(strategy, market_feature_frame, current_timestamp, daily_regime_map, trade_date, market_filter_frames=None):
    if getattr(strategy, "name", "") == config.ORVWAP_STRATEGY_NAME:
        return _resolve_orvwap_regime(market_filter_frames, current_timestamp)

    if getattr(config, "USE_DAILY_REGIME", False) or getattr(strategy, "name", "") == "daily_trend_v1":
        return daily_regime_for_date(
            daily_regime_map,
            trade_date,
            lag_days=int(getattr(config, "DAILY_REGIME_LAG_DAYS", 1)),
        )

    market_row = _latest_row_at_or_before(market_feature_frame, current_timestamp)
    return _classify_market_regime_from_row(market_row)


def _resolve_orvwap_regime(market_filter_frames, current_timestamp):
    spy_frame = market_filter_frames.get(config.ORVWAP_MARKET_FILTER_SYMBOL)
    qqq_frame = market_filter_frames.get(config.ORVWAP_TECH_FILTER_SYMBOL)

    spy_row = _latest_row_at_or_before(spy_frame, current_timestamp) if spy_frame is not None else None
    qqq_row = _latest_row_at_or_before(qqq_frame, current_timestamp) if qqq_frame is not None else None

    spy_above_vwap = bool(spy_row["above_vwap"]) if spy_row is not None else False
    qqq_above_vwap = bool(qqq_row["above_vwap"]) if qqq_row is not None else True
    spy_lower_lows = bool(spy_row.get("lower_lows_below_vwap", False)) if spy_row is not None else False

    if spy_row is None:
        return {
            "regime": "UNKNOWN",
            "trade_allowed": False,
            "reason": "missing SPY market data",
            "spy_above_vwap": False,
            "qqq_above_vwap": qqq_above_vwap,
        }

    if not spy_above_vwap or spy_lower_lows:
        reason = "SPY below VWAP" if not spy_above_vwap else "SPY making lower lows below VWAP"
        return {
            "regime": "RISK_OFF",
            "trade_allowed": False,
            "reason": reason,
            "spy_above_vwap": spy_above_vwap,
            "qqq_above_vwap": qqq_above_vwap,
        }

    return {
        "regime": "BULL_INTRADAY",
        "trade_allowed": True,
        "reason": "SPY above VWAP",
        "spy_above_vwap": spy_above_vwap,
        "qqq_above_vwap": qqq_above_vwap,
    }


def _should_force_close(strategy, current_timestamp) -> bool:
    if getattr(strategy, "holds_overnight", lambda: False)():
        return False
    return _is_force_close_time(current_timestamp, strategy)


def _is_entry_window_open(strategy, current_timestamp) -> bool:
    if hasattr(strategy, "entry_window_times"):
        start_time, end_time = strategy.entry_window_times()
        eastern_time = current_timestamp.to_pydatetime().astimezone(EASTERN).time()
        return _parse_time(start_time) <= eastern_time <= _parse_time(end_time)

    if getattr(strategy, "name", "") == "daily_trend_v1":
        eastern_time = current_timestamp.to_pydatetime().astimezone(EASTERN).time()
        return (
            _parse_time(config.SWING_ENTRY_START)
            <= eastern_time
            <= _parse_time(config.SWING_ENTRY_END)
        )
    return _is_buy_window_open(current_timestamp)


def _is_force_close_time(current_timestamp, strategy=None) -> bool:
    if strategy is not None and hasattr(strategy, "force_close_time"):
        eastern_time = current_timestamp.to_pydatetime().astimezone(EASTERN).time()
        return eastern_time >= _parse_time(strategy.force_close_time())
    eastern_time = current_timestamp.to_pydatetime().astimezone(EASTERN).time()
    return eastern_time >= _parse_time(config.FORCE_CLOSE_TIME)


def _log_signal_event(event_type, payload, shares=None, account_equity=None, signal_rows=None):
    row = dict(payload)
    row["position_size"] = shares
    row["account_equity"] = account_equity
    row["event_type"] = event_type
    if signal_rows is not None:
        signal_rows.append(row)
    if config.TRADING_MODE in {"SIGNAL_ONLY", "PAPER", "LIVE", "PAPER_TRADING"}:
        log_signal(event_type, row)


def _parse_time(value: str) -> time:
    hour, minute = value.split(":")
    return time(int(hour), int(minute))


def _regular_market_hours_only(data_frame):
    eastern_timestamps = data_frame["timestamp"].dt.tz_convert(EASTERN)
    market_times = eastern_timestamps.dt.time
    market_days = eastern_timestamps.dt.weekday < 5
    mask = (
        market_days
        & (market_times >= time(9, 30))
        & (market_times <= time(16, 0))
    )
    return data_frame[mask].reset_index(drop=True)


def _filter_date_window(data_frame, start_date, end_date):
    if data_frame.empty:
        return data_frame

    filtered = data_frame

    if start_date:
        start_timestamp = pd.Timestamp(start_date, tz="UTC")
        filtered = filtered[filtered["timestamp"] >= start_timestamp]

    if end_date:
        end_timestamp = pd.Timestamp(end_date, tz="UTC") + pd.Timedelta(days=1)
        filtered = filtered[filtered["timestamp"] < end_timestamp]

    return filtered.reset_index(drop=True)


def _ema_trend_label(features: dict) -> str:
    if float(features["ema_9"]) > float(features["ema_20"]) > float(features["ema_50"]):
        return "BULL_STACK"
    if float(features["ema_9"]) < float(features["ema_20"]) < float(features["ema_50"]):
        return "BEAR_STACK"
    return "MIXED"
