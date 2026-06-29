import config


class MomentumBreakoutStrategy:
    name = "momentum_breakout_v1"

    def evaluate_entry(self, symbol: str, features: dict, regime: dict) -> tuple[bool, dict]:
        if not regime.get("trade_allowed", False):
            return False, {"reason": f"bad regime: {regime.get('reason', 'unknown')}"}

        rejection = self._entry_rejection(features)
        if rejection is not None:
            return False, {"reason": rejection}

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
            "reason": "momentum breakout",
            "strategy_name": self.name,
            "setup_type": "breakout",
            "entry_price": close_price,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "risk_per_share": risk_per_share,
            "risk_reward": risk_reward
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
            return True, "2R take profit"

        if not bool(features.get("above_vwap", False)):
            return True, "lost VWAP"

        if not regime.get("trade_allowed", False):
            return True, "regime flip"

        if holding_minutes >= float(config.MAX_HOLD_MINUTES):
            return True, "max hold time"

        return False, "hold"

    def _entry_rejection(self, features: dict) -> str | None:
        close_price = float(features["close"])

        if not bool(features.get("above_vwap", False)):
            return "below VWAP"

        if not (
            float(features["ema_9"]) > float(features["ema_20"]) > float(features["ema_50"])
        ):
            return "EMA trend not aligned"

        if float(features["relative_volume"]) < float(config.MOMENTUM_RVOL_MIN):
            return "RVOL too low"

        rsi = float(features["rsi_14"])
        if rsi < float(config.RSI_MIN) or rsi > float(config.RSI_MAX):
            return "RSI outside momentum band"

        if float(features["atr_percent"]) > float(config.ATR_EXTREME_PERCENT):
            return "ATR too extreme"

        if float(features.get("spread_percent", 0.0)) > float(config.MAX_SPREAD_PERCENT):
            return "spread too wide"

        if float(features.get("volume_avg_20", 0.0)) < float(config.MIN_AVERAGE_VOLUME):
            return "volume too low"

        resistance = features.get("resistance_20")
        if getattr(config, "REQUIRE_BREAKOUT", True):
            if resistance is None or close_price <= float(resistance):
                return "not above resistance"

        return None

    def holds_overnight(self) -> bool:
        return False
