from collections import defaultdict

import config


class RiskGate:
    def __init__(self, starting_equity: float):
        self.starting_equity = float(starting_equity)
        self.peak_equity = float(starting_equity)
        self.trades_by_day = defaultdict(int)
        self.losing_streak = 0
        self.cooldown_until = None

    def update_equity(self, equity: float) -> None:
        self.peak_equity = max(self.peak_equity, float(equity))

    def record_closed_trade(self, timestamp, pnl_dollars: float) -> None:
        if pnl_dollars < 0:
            self.losing_streak += 1
        else:
            self.losing_streak = 0

        if self.losing_streak >= int(config.LOSING_STREAK_COOLDOWN):
            self.cooldown_until = timestamp

    def can_trade(self, timestamp, equity: float, day_pnl: float, positions: dict) -> tuple[bool, str]:
        if config.GLOBAL_KILL_SWITCH:
            return False, "global kill switch enabled"

        if config.TRADING_MODE != "PAPER_TRADING" and not config.LIVE_ENABLED:
            return False, "live trading disabled"

        equity_floor = float(config.PDT_MIN_EQUITY)
        if config.TRADING_MODE != "PAPER_TRADING":
            equity_floor = float(config.DO_NOT_TRADE_BELOW_EQUITY)

        if equity < equity_floor:
            return False, "below PDT equity floor"

        if day_pnl <= -float(config.MAX_DAILY_LOSS_DOLLARS):
            return False, "daily loss limit hit"

        drawdown = 0.0
        if self.peak_equity > 0:
            drawdown = (self.peak_equity - equity) / self.peak_equity

        if drawdown >= float(config.MAX_DRAWDOWN_PERCENT):
            return False, "max drawdown hit"

        trade_day = timestamp.date()
        if self.trades_by_day[trade_day] >= int(config.MAX_TRADES_PER_DAY):
            return False, "max trades per day hit"

        if len(positions) >= int(config.MAX_POSITIONS):
            return False, "max positions hit"

        return True, "allowed"

    def record_open_trade(self, timestamp) -> None:
        self.trades_by_day[timestamp.date()] += 1
