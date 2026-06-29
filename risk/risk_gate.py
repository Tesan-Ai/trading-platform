from collections import defaultdict

import config


class RiskGate:
    def __init__(self, starting_equity: float, strategy=None):
        self.starting_equity = float(starting_equity)
        self.peak_equity = float(starting_equity)
        self.trades_by_day = defaultdict(int)
        self.losing_trades_by_day = defaultdict(int)
        self.losing_streak = 0
        self.cooldown_until = None
        self.strategy = strategy

    def update_equity(self, equity: float) -> None:
        self.peak_equity = max(self.peak_equity, float(equity))

    def record_closed_trade(self, timestamp, pnl_dollars: float) -> None:
        trade_day = timestamp.date()
        if pnl_dollars < 0:
            self.losing_streak += 1
            self.losing_trades_by_day[trade_day] += 1
        else:
            self.losing_streak = 0

        max_losing = self._max_losing_trades_per_day()
        if self.losing_trades_by_day[trade_day] >= max_losing:
            self.cooldown_until = timestamp

    def can_trade(self, timestamp, equity: float, day_pnl: float, positions: dict) -> tuple[bool, str]:
        if config.GLOBAL_KILL_SWITCH:
            return False, "global kill switch enabled"

        if config.TRADING_MODE == "LIVE":
            if not config.ENABLE_LIVE_TRADING and not config.LIVE_ENABLED:
                return False, "live trading disabled"
        elif config.TRADING_MODE not in {"PAPER", "SIGNAL_ONLY", "PAPER_TRADING"}:
            return False, "unsupported trading mode"

        equity_floor = float(getattr(config, "DO_NOT_TRADE_BELOW_EQUITY", 0.0))
        if equity_floor > 0 and equity < equity_floor:
            return False, "below minimum equity floor"

        daily_loss_limit = max(
            float(config.MAX_DAILY_LOSS_DOLLARS),
            self.starting_equity * float(config.MAX_DAILY_LOSS_PERCENT),
        )
        if day_pnl <= -daily_loss_limit:
            return False, "daily loss limit hit"

        drawdown = 0.0
        if self.peak_equity > 0:
            drawdown = (self.peak_equity - equity) / self.peak_equity

        if drawdown >= float(config.MAX_DRAWDOWN_PERCENT):
            return False, "max drawdown hit"

        trade_day = timestamp.date()
        max_trades = self._max_trades_per_day()
        if self.trades_by_day[trade_day] >= max_trades:
            return False, "max trades per day hit"

        max_losing = self._max_losing_trades_per_day()
        if self.losing_trades_by_day[trade_day] >= max_losing:
            return False, "max losing trades per day hit"

        max_positions = self._max_positions()
        if len(positions) >= max_positions:
            return False, "max positions hit"

        return True, "allowed"

    def record_open_trade(self, timestamp) -> None:
        self.trades_by_day[timestamp.date()] += 1

    def _max_positions(self) -> int:
        if self.strategy is not None and hasattr(self.strategy, "max_positions"):
            return int(self.strategy.max_positions())
        return int(config.MAX_POSITIONS)

    def _max_trades_per_day(self) -> int:
        if self.strategy is not None and hasattr(self.strategy, "max_trades_per_day"):
            return int(self.strategy.max_trades_per_day())
        return int(config.MAX_TRADES_PER_DAY)

    def _max_losing_trades_per_day(self) -> int:
        if self.strategy is not None and hasattr(self.strategy, "max_losing_trades_per_day"):
            return int(self.strategy.max_losing_trades_per_day())
        return int(config.LOSING_STREAK_COOLDOWN)
