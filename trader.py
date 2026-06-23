from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo

import config
from ai_model import get_latest_price, score_stock
from market_scanner import scan_market
from risk_manager import calculate_position_size, can_open_new_position, check_daily_loss
from portfolio_manager import add_position, load_open_positions, close_position
from logger import log_trade, load_trade_log

EASTERN = ZoneInfo("America/New_York")


def normalize_time(current_time):
    if current_time is None:
        return datetime.now(EASTERN)

    if current_time.tzinfo is None:
        return current_time.replace(tzinfo=EASTERN)

    return current_time.astimezone(EASTERN)


def parse_stored_timestamp(timestamp_string):
    parsed_time = datetime.strptime(timestamp_string, "%Y-%m-%d %H:%M:%S")
    return parsed_time.replace(tzinfo=EASTERN)


def parse_config_time(value):
    hour, minute = value.split(":")
    return time(int(hour), int(minute))


def is_buy_window_open(current_time):
    now = normalize_time(current_time)
    start_time = parse_config_time(getattr(config, "BUY_START_TIME", "09:30"))
    end_time = parse_config_time(getattr(config, "BUY_END_TIME", "16:00"))
    return start_time <= now.time() <= end_time


def passes_hard_buy_filters(stock):
    if stock["symbol"] in getattr(config, "SYMBOL_BLACKLIST", set()):
        return False, "blacklisted"

    distance_to_ma50 = float(stock.get("distance_to_ma50", 999))
    return_3m = float(stock.get("return_3m", 0.0))
    return_5m = float(stock.get("return_5m", 0.0))
    return_15m = float(stock.get("return_15m", 0.0))
    relative_volume = float(stock.get("relative_volume", 0.0))
    vwap_distance = float(stock.get("vwap_distance", 0.0))
    pullback_position = float(stock.get("pullback_position", 1.0))
    ema_ratio = float(stock.get("ema_ratio", 0.0))
    bar_range_percent = float(stock.get("bar_range_percent", 1.0))

    if distance_to_ma50 < config.MIN_DISTANCE_TO_MA50:
        return False, "too weak below MA50"

    if distance_to_ma50 > config.MAX_DISTANCE_TO_MA50:
        return False, "too far above MA50"

    if return_3m < config.MIN_RETURN_3M:
        return False, "3m momentum too weak"

    if return_5m < config.MIN_RETURN_5M:
        return False, "5m momentum too weak"

    if return_15m < config.MIN_RETURN_15M:
        return False, "15m trend too weak"

    if relative_volume < config.MIN_RELATIVE_VOLUME:
        return False, "low volume"

    if relative_volume > getattr(config, "MAX_RELATIVE_VOLUME", float("inf")):
        return False, "volume too crowded"

    if ema_ratio < config.MIN_EMA_RATIO:
        return False, "EMA trend weak"

    if pullback_position < config.MIN_BREAKOUT_POSITION:
        return False, "too washed out"

    if pullback_position > config.MAX_BREAKOUT_POSITION:
        return False, "too extended"

    if bar_range_percent > config.MAX_BAR_RANGE_PERCENT:
        return False, "bar too volatile"

    if getattr(config, "REQUIRE_ABOVE_VWAP", False):
        if vwap_distance <= 0:
            return False, "below VWAP"

    return True, "passed"


def should_sell_position(position, latest_score, current_price, current_time):
    entry_price = float(position["entry_price"])
    entry_score = float(position.get("entry_score", latest_score))
    entry_timestamp = parse_stored_timestamp(position["entry_timestamp"])
    now = normalize_time(current_time)

    percent_change = (current_price - entry_price) / entry_price
    holding_minutes = (now - entry_timestamp).total_seconds() / 60.0
    holding_days = (now - entry_timestamp).total_seconds() / 86400.0
    score_drop = entry_score - latest_score

    if percent_change <= -config.STOP_LOSS_PERCENT:
        return True, "stop loss"

    if percent_change >= config.PROFIT_TARGET_PERCENT:
        return True, "profit target"

    if holding_minutes < config.MIN_HOLD_MINUTES:
        return False, "minimum hold"

    if percent_change >= config.PROFIT_PROTECTION_TRIGGER:
        if score_drop >= config.PROFIT_PROTECTION_SCORE_DROP:
            return True, "protecting profit"

        if latest_score <= config.SELL_SCORE_THRESHOLD:
            return True, "profit momentum faded"

    if holding_minutes >= config.WEAKNESS_EXIT_HOLD_MINUTES:
        if latest_score <= config.SELL_SCORE_THRESHOLD:
            return True, "momentum faded"

        if score_drop >= config.MIN_SCORE_DROP_TO_SELL:
            return True, "score dropped"

    if holding_minutes >= config.MAX_HOLD_MINUTES:
        return True, "time exit"

    if holding_days >= config.MAX_HOLD_DAYS:
        return True, "max hold"

    return False, "hold"


def get_last_sell_time(symbol):
    trades = load_trade_log()
    last_sell_time = None

    for trade in trades:
        if trade["symbol"] == symbol and trade["action"] == "SELL":
            trade_time = parse_stored_timestamp(trade["timestamp"])

            if last_sell_time is None or trade_time > last_sell_time:
                last_sell_time = trade_time

    return last_sell_time


def is_in_cooldown(symbol, current_time):
    last_sell_time = get_last_sell_time(symbol)

    if last_sell_time is None:
        return False

    now = normalize_time(current_time)
    cooldown_end_time = last_sell_time + timedelta(minutes=config.COOLDOWN_MINUTES)
    return now < cooldown_end_time


def count_symbol_buys_today(symbol, current_time):
    trades = load_trade_log()
    now = normalize_time(current_time)
    buys_today = 0

    for trade in trades:
        if trade["symbol"] != symbol or trade["action"] != "BUY":
            continue

        trade_time = parse_stored_timestamp(trade["timestamp"])

        if trade_time.date() == now.date():
            buys_today += 1

    return buys_today


def has_symbol_buy_capacity(symbol, current_time):
    max_buys = int(getattr(config, "MAX_BUYS_PER_SYMBOL_PER_DAY", 0))

    if max_buys <= 0:
        return True

    return count_symbol_buys_today(symbol, current_time) < max_buys


def process_sells(current_time):
    open_positions = load_open_positions()
    sold_trades = []

    print("\nChecking sells:\n")

    for position in open_positions:
        symbol = position["symbol"]
        shares = int(position["shares"])
        entry_price = float(position["entry_price"])

        stock_result = score_stock(symbol, current_time=current_time)

        if stock_result is not None:
            current_price = float(stock_result["close"])
            latest_score = float(stock_result["score"])
        else:
            latest_price = get_latest_price(symbol, current_time=current_time)

            if latest_price is None:
                continue

            current_price = latest_price
            latest_score = float(position.get("entry_score", 0.0))

        should_sell, reason = should_sell_position(
            position,
            latest_score,
            current_price,
            current_time
        )

        if should_sell:
            close_position(symbol)

            pnl = round((current_price - entry_price) * shares, 2)

            log_trade(
                "SELL",
                symbol,
                current_price,
                shares,
                round(current_price * shares, 2),
                latest_score,
                pnl,
                reason
            )

            sold_trades.append(symbol)

            print(
                f"SELL {symbol} | "
                f"Price={current_price:.2f} | "
                f"Score={latest_score:.2f} | "
                f"PnL={pnl:.2f} | "
                f"Reason={reason}"
            )

    return sold_trades


def count_buys_today(current_time):
    trades = load_trade_log()
    now = normalize_time(current_time)
    buys_today = 0

    for trade in trades:
        if trade["action"] != "BUY":
            continue

        trade_time = parse_stored_timestamp(trade["timestamp"])

        if trade_time.date() == now.date():
            buys_today += 1

    return buys_today


def qualifies_for_buy(stock, score_threshold):
    if float(stock["score"]) < score_threshold:
        return False

    if float(stock.get("intraday_score", stock["score"])) < config.MIN_INTRADAY_SCORE:
        return False

    passes, _reason = passes_hard_buy_filters(stock)
    return passes


def try_buy_candidates(
    candidates,
    score_threshold,
    current_time,
    open_symbols,
    current_positions,
    entry_reason,
):
    bought_trades = []

    for stock in candidates:
        symbol = stock["symbol"]

        if not qualifies_for_buy(stock, score_threshold):
            continue

        if symbol in open_symbols:
            continue

        if is_in_cooldown(symbol, current_time):
            continue

        if not has_symbol_buy_capacity(symbol, current_time):
            continue

        if not can_open_new_position(current_positions, current_time):
            break

        shares = calculate_position_size(stock["price"], current_time=current_time)

        if shares < 1:
            continue

        add_position(
            symbol=symbol,
            entry_price=stock["price"],
            shares=shares,
            entry_score=stock["score"],
            current_time=current_time,
        )

        log_trade(
            "BUY",
            symbol,
            stock["price"],
            shares,
            round(shares * stock["price"], 2),
            stock["score"],
            0.0,
            entry_reason,
        )

        bought_trades.append(symbol)

        print(
            f"BUY {symbol} | "
            f"Price={stock['price']:.2f} | "
            f"Score={stock['score']:.2f} | "
            f"Intraday={stock.get('intraday_score', stock['score']):.2f}"
        )

        current_positions += 1
        open_symbols.add(symbol)

    return bought_trades, current_positions, open_symbols


def run_trading_day(current_time=None, current_pnl=0.0):
    current_time = normalize_time(current_time)

    if not check_daily_loss(current_pnl):
        print("Stopped: daily loss limit")
        return [], []

    sold_trades = process_sells(current_time)

    if not is_buy_window_open(current_time):
        print("Outside buy window")
        return sold_trades, []

    open_positions = load_open_positions()
    open_symbols = {position["symbol"] for position in open_positions}
    current_positions = len(open_positions)

    print("\nScanning market...\n")

    candidates = scan_market(current_time=current_time)

    qualified = [
        stock for stock in candidates
        if qualifies_for_buy(stock, config.BUY_SCORE_THRESHOLD)
    ]
    qualified.sort(key=lambda item: item["score"], reverse=True)

    print(f"Qualified: {len(qualified)}")

    bought_trades, current_positions, open_symbols = try_buy_candidates(
        qualified,
        config.BUY_SCORE_THRESHOLD,
        current_time,
        open_symbols,
        current_positions,
        "momentum pullback entry",
    )

    if not bought_trades and not count_buys_today(current_time):
        now_time = current_time.time()
        relaxed_after = parse_config_time(getattr(config, "RELAXED_BUY_AFTER_TIME", "13:30"))

        if now_time >= relaxed_after and candidates:
            print("\nNo buys yet today — trying relaxed momentum threshold...\n")
            bought_trades, current_positions, open_symbols = try_buy_candidates(
                candidates,
                getattr(config, "RELAXED_BUY_SCORE_THRESHOLD", 5.5),
                current_time,
                open_symbols,
                current_positions,
                "relaxed momentum entry",
            )

    return sold_trades, bought_trades
