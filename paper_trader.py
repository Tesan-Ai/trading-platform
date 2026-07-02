from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

import config
from backtesting.profitability_replay import _is_entry_window_open, _position_size
from database import get_observability_store
from execution import PaperExecutionEngine
from features.daily_context import build_daily_regime_map, daily_regime_for_date
from features.feature_store import add_feature_columns, latest_features
from features.session_features import add_session_feature_columns, latest_session_features
from historical_data import get_data_client
from logger import log_trade
from market import evaluate_orvwap_market_filter
from portfolio_manager import load_open_positions
from risk.orvwap_risk_engine import OrvwapRiskEngine
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


def _prepare_live_features(symbol, frame, strategy):
    if getattr(strategy, "uses_session_features", False):
        return add_session_feature_columns(frame)
    return add_feature_columns(frame)


def _latest_strategy_features(symbol, frame, strategy):
    if getattr(strategy, "uses_session_features", False):
        return latest_session_features(symbol, frame)
    return latest_features(symbol, frame)


def _resolve_live_regime(strategy, symbol_frames, trade_date):
    if getattr(strategy, "name", "") == config.ORVWAP_STRATEGY_NAME:
        market_filter = evaluate_orvwap_market_filter(symbol_frames)
        return {
            "regime": market_filter["regime"],
            "trade_allowed": market_filter["allowed"],
            "reason": market_filter["reason"],
            "spy_above_vwap": market_filter["spy_above_vwap"],
            "qqq_above_vwap": market_filter["qqq_above_vwap"],
            "spy_status": market_filter["spy_status"],
            "qqq_status": market_filter["qqq_status"],
        }

    regime_symbol = getattr(config, "MARKET_REGIME_SYMBOL", "QQQ")
    regime_history = _fetch_regime_history(regime_symbol)
    daily_regime_map = build_daily_regime_map(regime_history)
    return daily_regime_for_date(
        daily_regime_map,
        trade_date,
        lag_days=int(getattr(config, "DAILY_REGIME_LAG_DAYS", 1)),
    )


def _parse_stored_timestamp(timestamp_string):
    parsed_time = datetime.strptime(timestamp_string, "%Y-%m-%d %H:%M:%S")
    return parsed_time.replace(tzinfo=EASTERN)


def run_paper_trading_cycle(current_time=None):
    current_time = current_time or datetime.now(EASTERN)
    strategy = get_strategy()
    default_symbols = list(config.ORVWAP_UNIVERSE) if getattr(strategy, "uses_session_features", False) else ["QQQ", "SPY"]
    symbols = list(getattr(config, "TRADE_SYMBOLS", default_symbols) or default_symbols)
    store = get_observability_store()
    bot_run_id = store.start_run(strategy.name, config.TRADING_MODE, symbols)
    executor = PaperExecutionEngine(bot_run_id)
    orvwap_risk_engine = OrvwapRiskEngine()

    if getattr(config, "PAPER_ONLY", True) and config.TRADING_MODE != "PAPER":
        message = f"Refusing to start: PAPER mode required, got {config.TRADING_MODE}"
        store.log_risk_event(bot_run_id, message, severity="critical", event_type="startup_block", blocked_trade=True, rule_name="paper_only")
        store.finish_run(bot_run_id, status="error", error_message=message)
        raise RuntimeError(message)

    try:
        store.heartbeat(bot_run_id, "running", "fetching_market_data")
        symbol_frames = _fetch_recent_bars(symbols)
        if not symbol_frames:
            print("No market data returned from Alpaca.")
            store.log(bot_run_id, "warning", "market_data", "No market data returned from Alpaca.")
            store.finish_run(bot_run_id, status="stopped")
            return [], []

        store.heartbeat(bot_run_id, "running", "preparing_features")
        featured = {
            symbol: _prepare_live_features(symbol, frame, strategy)
            for symbol, frame in symbol_frames.items()
        }
        current_prices = {
            symbol: float(frame.iloc[-1]["close"])
            for symbol, frame in featured.items()
            if not frame.empty
        }

        trade_date = current_time.date()
        regime = _resolve_live_regime(strategy, symbol_frames, trade_date)

        equity = _estimate_equity(current_prices)
        risk_gate = RiskGate(float(config.INITIAL_CAPITAL), strategy=strategy)
        risk_gate.update_equity(equity)

        sold = []
        bought = []

        print(f"\nStrategy: {strategy.name}")
        print(f"Mode: {config.TRADING_MODE}")
        print(f"Regime: {regime.get('regime')} ({regime.get('reason')})")

        store.heartbeat(bot_run_id, "running", "checking_exits")
        open_positions = load_open_positions()
        for position in open_positions:
            symbol = position["symbol"]
            if symbol not in featured:
                continue

            features = _latest_strategy_features(symbol, symbol_frames[symbol], strategy)
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
            order = executor.sell(position, current_price, reason, current_time)
            log_trade("SELL", symbol, current_price, shares, round(current_price * shares, 2), 0.0, order["realized_pnl"], reason)
            sold.append(symbol)
            print(f"SELL {symbol} @ {current_price:.2f} | PnL={order['realized_pnl']:.2f} | {reason}")

        if not _is_entry_window_open(strategy, pd.Timestamp(current_time)):
            store.heartbeat(bot_run_id, "running", "outside_entry_window")
            for symbol in symbols:
                features = _latest_strategy_features(symbol, symbol_frames[symbol], strategy) if symbol in symbol_frames else None
                if features and hasattr(strategy, "build_signal_context"):
                    details = strategy.build_signal_context(symbol, features, regime)
                    details["bot_run_id"] = bot_run_id
                    details["signal_type"] = "hold"
                    details["skip_reason"] = details.get("rejection_reason") or "outside entry window"
                    from signal_logger import log_signal

                    log_signal("HOLD", details)
            store.finish_run(bot_run_id, status="stopped")
            return sold, bought

        allowed, reason = risk_gate.can_trade(current_time, equity, 0.0, {item["symbol"]: item for item in load_open_positions()})
        if not allowed:
            print(f"Entry blocked: {reason}")
            store.log_risk_event(bot_run_id, reason, severity="warning", event_type="risk_block", rule_name="risk_gate")
            store.finish_run(bot_run_id, status="stopped")
            return sold, bought

        if not regime.get("trade_allowed", False):
            print("Entry blocked: market filter failed.")
            store.log_risk_event(bot_run_id, regime.get("reason", "market filter failed"), severity="warning", event_type="market_filter_block", rule_name="market_filter")

        open_symbols = {position["symbol"] for position in open_positions}
        cash = equity - sum(
            int(position["shares"]) * current_prices.get(position["symbol"], float(position["entry_price"]))
            for position in open_positions
        )

        store.heartbeat(bot_run_id, "running", "evaluating_entries")
        from signal_logger import log_signal

        for symbol in symbols:
            if symbol in open_symbols:
                continue

            if len(load_open_positions()) >= risk_gate._max_positions():
                store.log_risk_event(bot_run_id, "max positions hit", symbol=symbol, rule_name="max_positions")
                break

            features = _latest_strategy_features(symbol, symbol_frames[symbol], strategy) if symbol in symbol_frames else None
            if features is None:
                continue

            if hasattr(strategy, "build_signal_context"):
                details = strategy.build_signal_context(symbol, features, regime)
                passes = bool(details.get("entry_approved"))
                details["bot_run_id"] = bot_run_id
                details["account_equity"] = equity
                log_signal("BUY" if passes else "SKIP", details)
                if not passes:
                    print(f"REJECT {symbol}: {details.get('rejection_reason')}")
                    if "filter" in str(details.get("rejection_reason", "")).lower() or "vwap" in str(details.get("rejection_reason", "")).lower():
                        store.log_risk_event(bot_run_id, details.get("rejection_reason"), symbol=symbol, event_type="entry_rule_block", rule_name="entry_rules", raw_data=details)
                    continue
            else:
                passes, details = strategy.evaluate_entry(symbol, features, regime)
                if not passes:
                    continue

            risk_decision = orvwap_risk_engine.approve_entry(equity, cash, details, load_open_positions())
            details.update(risk_decision.as_dict())
            if not risk_decision.approved:
                details["trade_executed"] = False
                log_signal("SKIP", details)
                store.log_risk_event(bot_run_id, risk_decision.reason, symbol=symbol, event_type="risk_block", rule_name="orvwap_risk_engine", raw_data=details)
                print(f"RISK BLOCK {symbol}: {risk_decision.reason}")
                continue

            shares = risk_decision.final_quantity
            details["position_size"] = shares
            details["trade_executed"] = True
            log_signal("ENTRY", details)
            executor.buy(symbol, details, shares, current_time)
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
            risk_gate.record_open_trade(current_time)
            bought.append(symbol)
            cash -= shares * details["entry_price"]
            print(f"BUY {symbol} @ {details['entry_price']:.2f} | shares={shares} | {details['reason']}")

        store.finish_run(bot_run_id, status="stopped")
        return sold, bought
    except Exception as exc:
        store.log(bot_run_id, "error", "paper_trader", str(exc))
        store.finish_run(bot_run_id, status="error", error_message=str(exc))
        raise
