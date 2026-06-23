from datetime import datetime
from zoneinfo import ZoneInfo

import config
from portfolio_manager import load_open_positions
from equity_tracker import calculate_equity
from ai_model import score_stock

EASTERN = ZoneInfo("America/New_York")


def normalize_time(current_time):
    if current_time is None:
        return datetime.now(EASTERN)

    if current_time.tzinfo is None:
        return current_time.replace(tzinfo=EASTERN)

    return current_time.astimezone(EASTERN)


def get_open_positions_value(current_time=None):
    open_positions = load_open_positions()
    total_value = 0.0

    for position in open_positions:
        shares = float(position["shares"])
        entry_price = float(position["entry_price"])
        symbol = position["symbol"]

        stock_result = score_stock(symbol, current_time=current_time)

        if stock_result is not None:
            current_price = float(stock_result["close"])
        else:
            current_price = entry_price

        total_value += shares * current_price

    return total_value


def get_current_equity():
    current_equity = calculate_equity()

    if current_equity is None or current_equity <= 0:
        return float(config.INITIAL_CAPITAL)

    return float(current_equity)


def get_minimum_trading_equity():
    if config.TRADING_MODE == "PAPER_TRADING":
        return 0.0
    return float(getattr(config, "DO_NOT_TRADE_BELOW_EQUITY", 0.0))


def get_tradable_equity():
    current_equity = get_current_equity()
    minimum_trading_equity = get_minimum_trading_equity()
    tradable_equity = current_equity - minimum_trading_equity

    if tradable_equity <= 0:
        return 0.0

    return tradable_equity


def has_pdt_cushion():
    if config.TRADING_MODE == "PAPER_TRADING":
        return get_current_equity() >= float(config.PDT_MIN_EQUITY)
    return get_tradable_equity() > 0


def get_max_trade_dollars():
    return get_tradable_equity() * float(config.MAX_CAPITAL_PER_TRADE)


def get_max_total_exposure():
    return get_tradable_equity() * float(config.MAX_PORTFOLIO_EXPOSURE)


def get_remaining_exposure(current_time=None):
    max_total_exposure = get_max_total_exposure()
    current_exposure = get_open_positions_value(current_time=current_time)
    remaining_exposure = max_total_exposure - current_exposure

    if remaining_exposure < 0:
        return 0.0

    return remaining_exposure


def calculate_position_size(stock_price, current_time=None):
    stock_price = float(stock_price)

    if stock_price <= 0:
        return 0

    max_trade_dollars = get_max_trade_dollars()
    remaining_exposure = get_remaining_exposure(current_time=current_time)
    allowed_trade_dollars = min(max_trade_dollars, remaining_exposure)

    if allowed_trade_dollars < float(getattr(config, "MIN_TRADE_DOLLARS", 0.0)):
        return 0

    if allowed_trade_dollars < stock_price:
        return 0

    shares = int(allowed_trade_dollars // stock_price)

    if shares < 1:
        return 0

    return shares


def can_open_new_position(current_positions, current_time=None):
    if not has_pdt_cushion():
        return False

    if current_positions >= int(config.MAX_POSITIONS):
        return False

    if get_remaining_exposure(current_time=current_time) <= 0:
        return False

    return True


def check_daily_loss(current_pnl):
    if not has_pdt_cushion():
        return False

    percent_loss_limit = (
        float(config.INITIAL_CAPITAL) * float(config.MAX_DAILY_LOSS_PERCENT)
    )
    dollar_loss_limit = float(getattr(config, "MAX_DAILY_LOSS_DOLLARS", percent_loss_limit))
    max_daily_loss = min(percent_loss_limit, dollar_loss_limit)
    return float(current_pnl) > -max_daily_loss
