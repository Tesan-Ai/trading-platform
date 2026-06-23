from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

import config
from backtesting.profitability_replay import _is_entry_window_open
from features.daily_context import build_daily_regime_map, daily_regime_for_date
from features.feature_store import add_feature_columns, latest_features
from historical_data import get_data_client
from logger import log_trade
from portfolio_manager import add_position, close_position, load_open_positions
from risk.risk_gate import RiskGate
from strategies.factory import get_strategy

from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame

EASTERN = ZoneInfo("America/New_York")


def _estimate_equity(current_prices: dict) -> float:
    positions = load_open_positions()
    invested = sum(int(position["shares"]) * float(position["entry_price"]) for position in positions)
    cash = float(config.INITIAL_CAPITAL) - invested
    position_value = sum(
        int(position["shares"]) * current_prices.get(position["symbol"], float(position["entry_price"]))
        for position in positions
    )
    return cash + position_value


def _fetch_recent_bars(symbols, minutes_back=300):
    client = get_data_client()
    end_time = datetime.now(EASTERN)
    start_time = end_time - timedelta(minutes=minutes_back)

    request = StockBarsRequest(
        symbol_or_symbols=symbols,
        timeframe=TimeFrame.Minute,
        start=start_time,
        end=end_time,
        feed=config.ALPACA_DATA_FEED,
    )
    bars = client.get_stock_bars(request)

    symbol_frames = {}
    for symbol in symbols:
        if symbol not in bars.data:
            continue

        rows = []
        for bar in bars.data[symbol]:
            rows.append(
                {
                    "timestamp": bar.timestamp,
                    "open": float(bar.open),
                    "high": float(bar.high),
                    "low": float(bar.low),
                    "close": float(bar.close),
                    "volume": float(bar.volume),
                }
            )

        if rows:
            symbol_frames[symbol] = pd.DataFrame(rows).sort_values("timestamp").reset_index(drop=True)

    return symbol_frames


def _fetch_regime_history(symbol, days_back=320):
    client = get_data_client()
    end_time = datetime.now(EASTERN)
    start_time = end_time - timedelta(days=days_back)

    request = StockBarsRequest(
        symbol_or_symbols=[symbol],
        timeframe=TimeFrame.Minute,
        start=start_time,
        end=end_time,
        feed=config.ALPACA_DATA_FEED,
    )
    bars = client.get_stock_bars(request)

    if symbol not in bars.data:
        return pd.DataFrame()

    rows = []
    for bar in bars.data[symbol]:
        rows.append(
            {
                "timestamp": bar.timestamp,
                "open": float(bar.open),
                "high": float(bar.high),
                "low": float(bar.low),
                "close": float(bar.close),
                "volume": float(bar.volume),
            }
        )

    return pd.DataFrame(rows).sort_values("timestamp").reset_index(drop=True)


def _position_size(cash: float, price: float) -> int:
    trade_dollars = min(
        cash * float(config.MAX_CAPITAL_PER_TRADE),
        cash * float(config.MAX_PORTFOLIO_EXPOSURE),
    )
    if trade_dollars < float(config.MIN_TRADE_DOLLARS) or price <= 0:
        return 0
    return int(trade_dollars // price)


def _parse_stored_timestamp(timestamp_string):
    parsed_time = datetime.strptime(timestamp_string, "%Y-%m-%d %H:%M:%S")
    return parsed_time.replace(tzinfo=EASTERN)


def run_paper_trading_cycle(current_time=None):
    current_time = current_time or datetime.now(EASTERN)
    strategy = get_strategy()
    symbols = list(getattr(config, "TRADE_SYMBOLS", ["QQQ", "SPY"]))
    regime_symbol = getattr(config, "MARKET_REGIME_SYMBOL", "QQQ")

    symbol_frames = _fetch_recent_bars(symbols)
    if not symbol_frames:
        print("No market data returned from Alpaca.")
        return [], []

    featured = {
        symbol: add_feature_columns(frame)
        for symbol, frame in symbol_frames.items()
    }
    current_prices = {
        symbol: float(frame.iloc[-1]["close"])
        for symbol, frame in featured.items()
        if not frame.empty
    }

    regime_history = _fetch_regime_history(regime_symbol)
    daily_regime_map = build_daily_regime_map(regime_history)
    trade_date = current_time.date()
    regime = daily_regime_for_date(
        daily_regime_map,
        trade_date,
        lag_days=int(getattr(config, "DAILY_REGIME_LAG_DAYS", 1)),
    )

    equity = _estimate_equity(current_prices)
    risk_gate = RiskGate(float(config.INITIAL_CAPITAL))
    risk_gate.update_equity(equity)

    sold = []
    bought = []

    print(f"\nStrategy: {strategy.name}")
    print(f"Regime: {regime.get('regime')} ({regime.get('reason')})")

    open_positions = load_open_positions()
    for position in open_positions:
        symbol = position["symbol"]
        if symbol not in featured:
            continue

        features = latest_features(symbol, symbol_frames[symbol])
        if features is None:
            continue

        entry_timestamp = _parse_stored_timestamp(position["entry_timestamp"])
        holding_minutes = (current_time - entry_timestamp).total_seconds() / 60.0
        stop_loss = float(position["entry_price"]) * (1 - float(config.SWING_STOP_LOSS_PERCENT))
        take_profit = float(position["entry_price"]) * (1 + float(config.SWING_PROFIT_TARGET_PERCENT))
        position_details = {
            "entry_price": float(position["entry_price"]),
            "stop_loss": stop_loss,
            "take_profit": take_profit,
        }

        should_exit, reason = strategy.evaluate_exit(
            position_details,
            features,
            regime,
            holding_minutes,
            in_open_window=_is_entry_window_open(strategy, pd.Timestamp(current_time)),
        )

        if not should_exit:
            continue

        current_price = float(features["close"])
        shares = int(position["shares"])
        close_position(symbol)
        pnl = round((current_price - float(position["entry_price"])) * shares, 2)
        log_trade("SELL", symbol, current_price, shares, round(current_price * shares, 2), 0.0, pnl, reason)
        sold.append(symbol)
        print(f"SELL {symbol} @ {current_price:.2f} | PnL={pnl:.2f} | {reason}")

    if not _is_entry_window_open(strategy, pd.Timestamp(current_time)):
        return sold, bought

    allowed, reason = risk_gate.can_trade(current_time, equity, 0.0, {item["symbol"]: item for item in load_open_positions()})
    if not allowed:
        print(f"Entry blocked: {reason}")
        return sold, bought

    if not regime.get("trade_allowed", False):
        print("Entry blocked: daily regime not bullish.")
        return sold, bought

    open_symbols = {position["symbol"] for position in load_open_positions()}
    cash = equity - sum(
        int(position["shares"]) * current_prices.get(position["symbol"], float(position["entry_price"]))
        for position in load_open_positions()
    )

    for symbol in symbols:
        if symbol in open_symbols:
            continue

        if len(load_open_positions()) >= int(config.MAX_POSITIONS):
            break

        features = latest_features(symbol, symbol_frames[symbol])
        if features is None:
            continue

        passes, details = strategy.evaluate_entry(symbol, features, regime)
        if not passes:
            continue

        shares = _position_size(cash, float(details["entry_price"]))
        if shares < 1:
            continue

        add_position(
            symbol=symbol,
            entry_price=details["entry_price"],
            shares=shares,
            entry_score=0.0,
            current_time=current_time,
        )
        log_trade(
            "BUY",
            symbol,
            details["entry_price"],
            shares,
            round(shares * details["entry_price"], 2),
            0.0,
            0.0,
            details["reason"],
        )
        bought.append(symbol)
        cash -= shares * details["entry_price"]
        print(f"BUY {symbol} @ {details['entry_price']:.2f} | shares={shares} | {details['reason']}")

    return sold, bought
