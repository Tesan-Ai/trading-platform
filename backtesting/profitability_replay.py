from datetime import time
from typing import Dict, List
import os

import pandas as pd
from zoneinfo import ZoneInfo

import config
from analytics.trade_analytics import build_trade_rows, calculate_report
from features.daily_context import build_daily_regime_map, daily_regime_for_date
from features.feature_store import add_feature_columns, latest_features
from regime.market_regime import classify_market_regime
from risk.risk_gate import RiskGate
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
            "market_regime": regime.get("regime"),
            "sector": features.get("sector", "UNKNOWN"),
            "spread_percent": features.get("spread_percent"),
            "volume": features.get("volume"),
            "macd_slope": features.get("macd_slope"),
            "breakout_distance": features.get("breakout_distance")
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
    featured_symbol_data = {
        symbol: add_feature_columns(data_frame).dropna().reset_index(drop=True)
        for symbol, data_frame in symbol_data.items()
    }
    featured_symbol_data = {
        symbol: data_frame
        for symbol, data_frame in featured_symbol_data.items()
        if not data_frame.empty
    }
    timeline = build_timeline(featured_symbol_data)
    market_feature_frame = _build_market_feature_frame(symbol_data)
    regime_source = symbol_data.get(config.MARKET_REGIME_SYMBOL)
    if regime_source is None or regime_source.empty:
        regime_source = _build_market_proxy_from_full_data(symbol_data)
    daily_regime_map = build_daily_regime_map(regime_source)
    portfolio = ProfitabilityPortfolio(starting_cash)
    strategy = strategy or get_strategy()
    risk_gate = RiskGate(starting_cash)
    entries_by_symbol_day = set()
    exit_checked_dates = set()

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

        candidates = _rank_candidates(featured_symbol_data, current_timestamp, strategy, latest_regime)
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

            shares = _position_size(portfolio.cash, candidate["entry_details"]["entry_price"])
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

        _record_equity(portfolio, current_timestamp, current_prices)

    trade_rows = build_trade_rows(portfolio.trade_log)
    report = calculate_report(trade_rows, portfolio.equity_curve)

    return {
        "portfolio": portfolio,
        "trade_rows": trade_rows,
        "report": report,
        "latest_regime": latest_regime
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


def _rank_candidates(featured_symbol_data, current_timestamp, strategy, regime) -> list[dict]:
    candidates = []

    for symbol, data_frame in featured_symbol_data.items():
        features = _features_at_or_before(symbol, data_frame, current_timestamp)
        if features is None:
            continue

        passes, details = strategy.evaluate_entry(symbol, features, regime)
        if not passes:
            continue

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


def _build_market_feature_frame(symbol_data):
    for market_symbol in ("SPY", "QQQ"):
        if market_symbol in symbol_data and not symbol_data[market_symbol].empty:
            return add_feature_columns(symbol_data[market_symbol]).dropna().reset_index(drop=True)

    return add_feature_columns(
        _build_market_proxy_from_full_data(symbol_data)
    ).dropna().reset_index(drop=True)


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


def _position_size(cash: float, price: float) -> int:
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


def _resolve_regime(strategy, market_feature_frame, current_timestamp, daily_regime_map, trade_date):
    if getattr(config, "USE_DAILY_REGIME", False) or getattr(strategy, "name", "") == "daily_trend_v1":
        return daily_regime_for_date(
            daily_regime_map,
            trade_date,
            lag_days=int(getattr(config, "DAILY_REGIME_LAG_DAYS", 1)),
        )

    market_row = _latest_row_at_or_before(market_feature_frame, current_timestamp)
    return _classify_market_regime_from_row(market_row)


def _should_force_close(strategy, current_timestamp) -> bool:
    if getattr(strategy, "holds_overnight", lambda: False)():
        return False
    return _is_force_close_time(current_timestamp)


def _is_entry_window_open(strategy, current_timestamp) -> bool:
    if getattr(strategy, "name", "") == "daily_trend_v1":
        eastern_time = current_timestamp.to_pydatetime().astimezone(EASTERN).time()
        return (
            _parse_time(config.SWING_ENTRY_START)
            <= eastern_time
            <= _parse_time(config.SWING_ENTRY_END)
        )
    return _is_buy_window_open(current_timestamp)


def _is_force_close_time(current_timestamp) -> bool:
    eastern_time = current_timestamp.to_pydatetime().astimezone(EASTERN).time()
    return eastern_time >= _parse_time(config.FORCE_CLOSE_TIME)


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
