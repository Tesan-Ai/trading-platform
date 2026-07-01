import config

from .bull_day_trade import BullDayTradeStrategy
from .momentum_scan import MomentumScanStrategy
from .daily_trend import DailyTrendStrategy
from .momentum_breakout import MomentumBreakoutStrategy
from .opening_range_vwap_momentum import OpeningRangeVwapMomentumStrategy
from .orb_pullback_continuation import OrbPullbackContinuationStrategy


STRATEGY_REGISTRY = {
    "daily_trend_v1": DailyTrendStrategy,
    "momentum_scan_v1": MomentumScanStrategy,
    "momentum_breakout_v1": MomentumBreakoutStrategy,
    "bull_day_trade_v1": BullDayTradeStrategy,
    "opening_range_vwap_momentum_v1": OpeningRangeVwapMomentumStrategy,
    # RESEARCH ONLY. See strategies/orb_pullback_continuation.py -- this
    # strategy intentionally never trades through the generic replay engine
    # (evaluate_entry always rejects); real backtests run through the
    # dedicated backtesting/orb_pbc_engine.py via orb_pbc_runner.py.
    "orb_pullback_continuation_v1": OrbPullbackContinuationStrategy,
}


def get_strategy(name: str | None = None):
    strategy_name = name or getattr(config, "ACTIVE_STRATEGY", "daily_trend_v1")
    strategy_class = STRATEGY_REGISTRY.get(strategy_name)

    if strategy_class is None:
        raise ValueError(f"Unknown strategy: {strategy_name}")

    return strategy_class()
