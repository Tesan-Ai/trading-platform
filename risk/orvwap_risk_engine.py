from dataclasses import dataclass

import config


@dataclass
class RiskDecision:
    approved: bool
    reason: str
    risk_per_trade: float
    dollar_risk: float
    calculated_quantity: int
    final_quantity: int
    stop_price: float | None
    take_profit_price: float | None

    def as_dict(self) -> dict:
        return {
            "approved": self.approved,
            "reason": self.reason,
            "risk_per_trade": self.risk_per_trade,
            "dollar_risk": self.dollar_risk,
            "calculated_quantity": self.calculated_quantity,
            "final_quantity": self.final_quantity,
            "stop_price": self.stop_price,
            "take_profit_price": self.take_profit_price,
        }


class OrvwapRiskEngine:
    def approve_entry(self, equity: float, cash: float, signal: dict, open_positions: list, trades_today: int = 0, losses_today: int = 0) -> RiskDecision:
        if getattr(config, "PAPER_ONLY", True) and config.TRADING_MODE != "PAPER":
            return self._blocked("paper mode required", equity, signal)

        if config.GLOBAL_KILL_SWITCH:
            return self._blocked("kill switch enabled", equity, signal)

        if len(open_positions) >= int(config.ORVWAP_MAX_POSITIONS):
            return self._blocked("max open positions hit", equity, signal)

        if trades_today >= int(config.ORVWAP_MAX_TRADES_PER_DAY):
            return self._blocked("max trades per day hit", equity, signal)

        if losses_today >= int(config.ORVWAP_MAX_LOSING_TRADES_PER_DAY):
            return self._blocked("max losing trades per day hit", equity, signal)

        spread = signal.get("spread_percentage", signal.get("spread"))
        if spread is not None and float(spread) > float(config.ORVWAP_MAX_SPREAD_PCT):
            return self._blocked("spread too wide", equity, signal)

        extension = signal.get("distance_from_vwap_atr")
        if extension is not None and float(extension) > float(config.ORVWAP_MAX_VWAP_EXTENSION_ATR):
            return self._blocked("extended too far from VWAP", equity, signal)

        entry_price = float(signal["entry_price"])
        stop_price = float(signal["stop_price"])
        take_profit = float(signal["target_price"])
        stop_distance = entry_price - stop_price
        if stop_distance <= 0:
            return self._blocked("invalid stop distance", equity, signal)

        risk_per_trade = float(config.ORVWAP_RISK_PER_TRADE_PCT)
        dollar_risk = float(equity) * risk_per_trade
        calculated_quantity = int(dollar_risk // stop_distance)
        cash_quantity = int(float(cash) // entry_price)
        final_quantity = max(0, min(calculated_quantity, cash_quantity))
        if final_quantity < 1:
            return RiskDecision(False, "quantity below 1", risk_per_trade, dollar_risk, calculated_quantity, final_quantity, stop_price, take_profit)

        return RiskDecision(True, "approved", risk_per_trade, dollar_risk, calculated_quantity, final_quantity, stop_price, take_profit)

    def _blocked(self, reason: str, equity: float, signal: dict) -> RiskDecision:
        return RiskDecision(
            False,
            reason,
            float(config.ORVWAP_RISK_PER_TRADE_PCT),
            float(equity) * float(config.ORVWAP_RISK_PER_TRADE_PCT),
            0,
            0,
            signal.get("stop_price"),
            signal.get("target_price"),
        )
