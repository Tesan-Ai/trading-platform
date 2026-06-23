import config


class DailyTrendStrategy:
    name = "daily_trend_v1"

    def evaluate_entry(self, symbol: str, features: dict, regime: dict) -> tuple[bool, dict]:
        if symbol not in getattr(config, "TRADE_SYMBOLS", []):
            return False, {"reason": "symbol not in trade universe"}

        if not regime.get("trade_allowed", False):
            return False, {"reason": f"regime blocked: {regime.get('reason', 'unknown')}"}

        close_price = float(features["close"])
        stop_loss = close_price * (1 - float(config.SWING_STOP_LOSS_PERCENT))
        risk_per_share = close_price - stop_loss

        if risk_per_share <= 0:
            return False, {"reason": "invalid risk"}

        take_profit = close_price * (1 + float(config.SWING_PROFIT_TARGET_PERCENT))
        reward_per_share = take_profit - close_price
        risk_reward = reward_per_share / risk_per_share

        return True, {
            "reason": "daily trend entry",
            "strategy_name": self.name,
            "setup_type": "daily_trend",
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
            return True, "swing stop loss"

        if close_price >= float(position["take_profit"]):
            return True, "swing profit target"

        if in_open_window and not regime.get("trade_allowed", False):
            return True, "daily trend ended"

        return False, "hold"

    def holds_overnight(self) -> bool:
        return True
