import config

from .bull_day_trade import BullDayTradeStrategy
from .momentum_scan import MomentumScanStrategy
from .daily_trend import DailyTrendStrategy
from .momentum_breakout import MomentumBreakoutStrategy


STRATEGY_REGISTRY = {
    "daily_trend_v1": DailyTrendStrategy,
    "momentum_scan_v1": MomentumScanStrategy,
    "momentum_breakout_v1": MomentumBreakoutStrategy,
    "bull_day_trade_v1": BullDayTradeStrategy,
}


def get_strategy(name: str | None = None):
    strategy_name = name or getattr(config, "ACTIVE_STRATEGY", "daily_trend_v1")
    strategy_class = STRATEGY_REGISTRY.get(strategy_name)

    if strategy_class is None:
        raise ValueError(f"Unknown strategy: {strategy_name}")

    return strategy_class()
