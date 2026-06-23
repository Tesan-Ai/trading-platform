from datetime import datetime, time
from typing import Dict, List
import os

import pandas as pd
from zoneinfo import ZoneInfo

import config
from ai_model import build_trend_metrics_from_frame, score_data_frame

EASTERN = ZoneInfo("America/New_York")


class ReplayPortfolio:
    def __init__(self, starting_cash: float):
        self.cash = starting_cash
        self.positions = {}
        self.trade_log = []
        self.equity_curve = []
        self.last_sell_times = {}
        self.buy_counts_by_symbol_day = {}

    def get_total_position_value(self, current_prices: Dict[str, float]) -> float:
        total_value = 0.0

        for symbol, position in self.positions.items():
            if symbol in current_prices:
                total_value += position["shares"] * current_prices[symbol]

        return total_value

    def get_total_equity(self, current_prices: Dict[str, float]) -> float:
        return self.cash + self.get_total_position_value(current_prices)

    def buy(
        self,
        timestamp: datetime,
        symbol: str,
        price: float,
        shares: int,
        score: float,
        metadata: dict | None = None
    ) -> None:
        if shares <= 0:
            return

        fill_price = price * (1 + float(getattr(config, "BACKTEST_SLIPPAGE_PERCENT", 0.0)))
        cost = fill_price * shares
        if cost > self.cash:
            return

        self.cash -= cost
        self.positions[symbol] = {
            "shares": shares,
            "entry_price": fill_price,
            "entry_timestamp": timestamp,
            "score": score
        }

        trade = {
            "timestamp": timestamp,
            "action": "BUY",
            "symbol": symbol,
            "price": fill_price,
            "shares": shares,
            "score": score
        }

        if metadata:
            trade.update(metadata)

        self.trade_log.append(trade)

        trade_day = timestamp.astimezone(EASTERN).date()
        key = (symbol, trade_day)
        self.buy_counts_by_symbol_day[key] = self.buy_counts_by_symbol_day.get(key, 0) + 1

    def sell(self, timestamp: datetime, symbol: str, price: float, reason: str) -> None:
        if symbol not in self.positions:
            return

        position = self.positions[symbol]
        shares = position["shares"]
        fill_price = price * (1 - float(getattr(config, "BACKTEST_SLIPPAGE_PERCENT", 0.0)))
        proceeds = fill_price * shares
        pnl_percent = (fill_price - position["entry_price"]) / position["entry_price"]

        self.cash += proceeds

        self.trade_log.append({
            "timestamp": timestamp,
            "action": "SELL",
            "symbol": symbol,
            "price": fill_price,
            "shares": shares,
            "reason": reason,
            "entry_price": position["entry_price"],
            "pnl_percent": pnl_percent
        })

        self.last_sell_times[symbol] = timestamp
        del self.positions[symbol]


def load_symbol_data(symbols: List[str], data_dir: str) -> Dict[str, pd.DataFrame]:
    loaded = {}

    for symbol in symbols:
        file_path = os.path.join(data_dir, f"{symbol}.csv")
        if not os.path.exists(file_path):
            print(f"Missing historical file: {file_path}")
            continue

        data_frame = pd.read_csv(file_path)
        data_frame["timestamp"] = pd.to_datetime(data_frame["timestamp"], utc=True)
        data_frame = data_frame.sort_values("timestamp").reset_index(drop=True)

        loaded[symbol] = data_frame

    return loaded


def build_replay_timeline(symbol_data: Dict[str, pd.DataFrame]) -> List[pd.Timestamp]:
    all_timestamps = set()

    for data_frame in symbol_data.values():
        for timestamp in data_frame["timestamp"]:
            all_timestamps.add(timestamp)

    timeline = sorted(all_timestamps)
    return timeline


def should_sell_position(position: dict, latest_score: float, current_price: float, current_time: datetime) -> tuple[bool, str]:
    entry_price = float(position["entry_price"])
    entry_timestamp = position["entry_timestamp"]

    percent_change = (current_price - entry_price) / entry_price
    holding_minutes = (current_time - entry_timestamp).total_seconds() / 60.0

    if percent_change >= config.PROFIT_TARGET_PERCENT:
        return True, "profit target reached"

    if percent_change <= -config.STOP_LOSS_PERCENT:
        return True, "stop loss triggered"

    if latest_score <= config.SELL_SCORE_THRESHOLD:
        return True, "score dropped below sell threshold"

    max_hold_minutes = getattr(config, "MAX_HOLD_MINUTES", 390)
    if holding_minutes >= max_hold_minutes:
        return True, "max hold time reached"

    return False, "hold"


def parse_config_time(value: str) -> time:
    hour, minute = value.split(":")
    return time(int(hour), int(minute))


def is_buy_window_open(current_timestamp: pd.Timestamp) -> bool:
    eastern_time = current_timestamp.to_pydatetime().astimezone(EASTERN).time()
    start_time = parse_config_time(getattr(config, "BUY_START_TIME", "09:30"))
    end_time = parse_config_time(getattr(config, "BUY_END_TIME", "16:00"))
    return start_time <= eastern_time <= end_time


def is_force_close_time(current_timestamp: pd.Timestamp) -> bool:
    eastern_time = current_timestamp.to_pydatetime().astimezone(EASTERN).time()
    force_close_time = parse_config_time(getattr(config, "FORCE_CLOSE_TIME", "15:55"))
    return eastern_time >= force_close_time


def is_in_cooldown(portfolio: ReplayPortfolio, symbol: str, current_timestamp: pd.Timestamp) -> bool:
    last_sell_time = portfolio.last_sell_times.get(symbol)

    if last_sell_time is None:
        return False

    cooldown_minutes = int(getattr(config, "COOLDOWN_MINUTES", 0))

    if cooldown_minutes <= 0:
        return False

    elapsed_minutes = (
        current_timestamp.to_pydatetime() - last_sell_time
    ).total_seconds() / 60.0
    return elapsed_minutes < cooldown_minutes


def has_symbol_buy_capacity(portfolio: ReplayPortfolio, symbol: str, current_timestamp: pd.Timestamp) -> bool:
    max_buys = int(getattr(config, "MAX_BUYS_PER_SYMBOL_PER_DAY", 0))

    if max_buys <= 0:
        return True

    trade_day = current_timestamp.to_pydatetime().astimezone(EASTERN).date()
    return portfolio.buy_counts_by_symbol_day.get((symbol, trade_day), 0) < max_buys


def passes_replay_buy_filters(candidate: dict) -> bool:
    if candidate["symbol"] in getattr(config, "SYMBOL_BLACKLIST", set()):
        return False

    if float(candidate.get("distance_to_ma50", 999)) < config.MIN_DISTANCE_TO_MA50:
        return False

    if float(candidate.get("distance_to_ma50", 999)) > config.MAX_DISTANCE_TO_MA50:
        return False

    if float(candidate.get("return_3m", 0.0)) < config.MIN_RETURN_3M:
        return False

    if float(candidate.get("return_5m", 0.0)) < config.MIN_RETURN_5M:
        return False

    if float(candidate.get("return_15m", 0.0)) < config.MIN_RETURN_15M:
        return False

    if float(candidate.get("relative_volume", 0.0)) < config.MIN_RELATIVE_VOLUME:
        return False

    if float(candidate.get("relative_volume", 0.0)) > getattr(config, "MAX_RELATIVE_VOLUME", float("inf")):
        return False

    if float(candidate.get("ema_ratio", 0.0)) < config.MIN_EMA_RATIO:
        return False

    if float(candidate.get("pullback_position", 1.0)) < config.MIN_BREAKOUT_POSITION:
        return False

    if float(candidate.get("pullback_position", 1.0)) > config.MAX_BREAKOUT_POSITION:
        return False

    if float(candidate.get("bar_range_percent", 1.0)) > config.MAX_BAR_RANGE_PERCENT:
        return False

    if getattr(config, "REQUIRE_ABOVE_VWAP", False):
        if float(candidate.get("vwap_distance", 0.0)) <= 0:
            return False

    return True


def calculate_position_size(cash: float, price: float) -> int:
    allocation_percent = getattr(config, "MAX_CAPITAL_PER_TRADE", 0.08)
    dollars_to_use = cash * allocation_percent

    if price <= 0:
        return 0

    shares = int(dollars_to_use // price)
    return max(shares, 0)


def run_replay(symbols: List[str], data_dir: str = "historical_data", starting_cash: float = 100000.0):
    symbol_data = load_symbol_data(symbols, data_dir)
    timeline = build_replay_timeline(symbol_data)

    portfolio = ReplayPortfolio(starting_cash=starting_cash)

    for current_timestamp in timeline:
        current_prices = {}
        scored_candidates = []

        for symbol, full_data_frame in symbol_data.items():
            visible_data = full_data_frame[full_data_frame["timestamp"] <= current_timestamp].copy()

            if len(visible_data) < 20:
                continue

            current_prices[symbol] = float(visible_data.iloc[-1]["close"])

            trend_metrics = build_trend_metrics_from_frame(symbol, visible_data)

            if trend_metrics is None:
                continue

            intraday_window = visible_data.tail(
                getattr(config, "MODEL_MINUTES_BACK", 180)
            ).copy()

            score_result = score_data_frame(symbol, intraday_window, trend_metrics)

            if score_result is None:
                continue

            scored_candidates.append(score_result)

        # Sell pass
        open_symbols = list(portfolio.positions.keys())
        for symbol in open_symbols:
            if symbol not in current_prices:
                continue

            latest_score = None
            for candidate in scored_candidates:
                if candidate["symbol"] == symbol:
                    latest_score = candidate["score"]
                    break

            if latest_score is None:
                latest_score = float(portfolio.positions[symbol].get("score", 0.0))

            current_price = current_prices[symbol]
            should_sell, reason = should_sell_position(
                portfolio.positions[symbol],
                latest_score,
                current_price,
                current_timestamp.to_pydatetime()
            )

            if should_sell:
                portfolio.sell(current_timestamp.to_pydatetime(), symbol, current_price, reason)

        # Buy pass
        if is_force_close_time(current_timestamp):
            for symbol in list(portfolio.positions.keys()):
                if symbol in current_prices:
                    portfolio.sell(
                        current_timestamp.to_pydatetime(),
                        symbol,
                        current_prices[symbol],
                        "end of day close"
                    )

            equity = portfolio.get_total_equity(current_prices)
            portfolio.equity_curve.append({
                "timestamp": current_timestamp,
                "equity": equity,
                "cash": portfolio.cash,
                "positions": len(portfolio.positions)
            })
            continue

        if not is_buy_window_open(current_timestamp):
            equity = portfolio.get_total_equity(current_prices)
            portfolio.equity_curve.append({
                "timestamp": current_timestamp,
                "equity": equity,
                "cash": portfolio.cash,
                "positions": len(portfolio.positions)
            })
            continue

        scored_candidates.sort(key=lambda item: item["score"], reverse=True)

        for candidate in scored_candidates:
            symbol = candidate["symbol"]

            if symbol in portfolio.positions:
                continue

            if is_in_cooldown(portfolio, symbol, current_timestamp):
                continue

            if not has_symbol_buy_capacity(portfolio, symbol, current_timestamp):
                continue

            if len(portfolio.positions) >= config.MAX_POSITIONS:
                break

            if candidate["score"] < config.BUY_SCORE_THRESHOLD:
                continue

            if not passes_replay_buy_filters(candidate):
                continue

            shares = calculate_position_size(portfolio.cash, candidate["close"])

            if shares > 0:
                portfolio.buy(
                    current_timestamp.to_pydatetime(),
                    symbol,
                    float(candidate["close"]),
                    shares,
                    float(candidate["score"]),
                    {
                        "return_3m": candidate.get("return_3m"),
                        "return_5m": candidate.get("return_5m"),
                        "return_15m": candidate.get("return_15m"),
                        "return_30m": candidate.get("return_30m"),
                        "ema_ratio": candidate.get("ema_ratio"),
                        "relative_volume": candidate.get("relative_volume"),
                        "vwap_distance": candidate.get("vwap_distance"),
                        "pullback_position": candidate.get("pullback_position"),
                        "bar_range_percent": candidate.get("bar_range_percent"),
                        "distance_to_ma50": candidate.get("distance_to_ma50")
                    }
                )

        equity = portfolio.get_total_equity(current_prices)
        portfolio.equity_curve.append({
            "timestamp": current_timestamp,
            "equity": equity,
            "cash": portfolio.cash,
            "positions": len(portfolio.positions)
        })

    return portfolio
