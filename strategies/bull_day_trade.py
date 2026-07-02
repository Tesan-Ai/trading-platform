import config


class BullDayTradeStrategy:
    """Legacy intraday strategy kept for research sweeps."""

    name = "bull_day_trade_v1"

    def evaluate_entry(self, symbol: str, features: dict, regime: dict) -> tuple[bool, dict]:
        if not regime.get("trade_allowed", False):
            return False, {"reason": f"regime blocked: {regime.get('reason', 'unknown')}"}

        close_price = float(features["close"])
        atr = float(features["atr_14"])
        stop_loss = close_price - (atr * float(config.ATR_STOP_MULTIPLE))
        risk_per_share = close_price - stop_loss

        if risk_per_share <= 0:
            return False, {"reason": "invalid risk"}

        take_profit = close_price + (risk_per_share * float(config.RISK_REWARD_MINIMUM))
        reward_per_share = take_profit - close_price
        risk_reward = reward_per_share / risk_per_share

        if risk_reward < float(config.RISK_REWARD_MINIMUM):
            return False, {"reason": "risk reward too low"}

        return True, {
            "reason": "bull day trade",
            "strategy_name": self.name,
            "setup_type": "day_trade",
            "entry_price": close_price,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "risk_per_share": risk_per_share,
            "risk_reward": risk_reward,
        }

    def evaluate_exit(
        self,
        position: dict,
        features: dict,
        regime: dict,
        holding_minutes: float,
        in_open_window: bool = False,
    ) -> tuple[bool, str]:
        close_price = float(features["close"])

        if close_price <= float(position["stop_loss"]):
            return True, "ATR stop loss"

        if close_price >= float(position["take_profit"]):
            return True, "take profit"

        if not regime.get("trade_allowed", False):
            return True, "regime flip"

        if holding_minutes >= float(config.MAX_HOLD_MINUTES):
            return True, "max hold time"

        return False, "hold"

    def holds_overnight(self) -> bool:
        return False
