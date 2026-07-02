from datetime import datetime
from zoneinfo import ZoneInfo

import config
from paper_trader import run_paper_trading_cycle
from strategy_allocator import apply_strategy_allocator
from strategies.factory import STRATEGY_REGISTRY
from trader import run_trading_day

EASTERN = ZoneInfo("America/New_York")

STRATEGY_FACTORY_STRATEGIES = {
    "daily_trend_v1",
    config.ORVWAP_STRATEGY_NAME,
    "momentum_breakout_v1",
    "bull_day_trade_v1",
}


def run_trading_cycle(current_time=None, current_pnl=0.0):
    allocator_decision = apply_strategy_allocator()
    if allocator_decision.get("status") in {"selected", "shadow_selected"}:
        print(
            "Strategy allocator:",
            allocator_decision["selected_strategy"],
            f"({allocator_decision.get('allocator_mode')})",
            "-",
            allocator_decision["reason"],
        )
    elif getattr(config, "AUTO_STRATEGY_SELECTION", False):
        print("Strategy allocator:", allocator_decision["status"], "-", allocator_decision["reason"])

    if config.ACTIVE_STRATEGY in STRATEGY_FACTORY_STRATEGIES:
        return run_paper_trading_cycle(current_time=current_time)

    if config.ACTIVE_STRATEGY in STRATEGY_REGISTRY and config.TRADING_MODE == "PAPER":
        return run_paper_trading_cycle(current_time=current_time)

    if current_time is None:
        current_time = datetime.now(EASTERN)

    return run_trading_day(current_time=current_time, current_pnl=current_pnl)
