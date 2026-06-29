import config


class OpeningRangeVwapMomentumStrategy:
    name = config.ORVWAP_STRATEGY_NAME
    uses_session_features = True

    TECH_SYMBOLS = set(config.ORVWAP_TECH_SYMBOLS)
    UNIVERSE = set(getattr(config, "ORVWAP_TRADE_SYMBOLS", config.ORVWAP_UNIVERSE))

    def entry_window_times(self) -> tuple[str, str]:
        return config.ORVWAP_ENTRY_START, config.ORVWAP_ENTRY_END

    def force_close_time(self) -> str:
        return config.ORVWAP_FORCE_CLOSE_TIME

    def max_positions(self) -> int:
        return int(config.ORVWAP_MAX_POSITIONS)

    def max_trades_per_day(self) -> int:
        return int(config.ORVWAP_MAX_TRADES_PER_DAY)

    def max_losing_trades_per_day(self) -> int:
        return int(config.ORVWAP_MAX_LOSING_TRADES_PER_DAY)

    def evaluate_entry(self, symbol: str, features: dict, regime: dict) -> tuple[bool, dict]:
        context = self.build_signal_context(symbol, features, regime)
        if not context["entry_approved"]:
            return False, context

        entry_price = float(features["close"])
        stop_loss = float(context["stop_price"])
        take_profit = float(context["target_price"])
        risk_per_share = entry_price - stop_loss

        if risk_per_share <= 0:
            context["entry_approved"] = False
            context["rejection_reason"] = "invalid stop below entry"
            return False, context

        reward_per_share = take_profit - entry_price
        risk_reward = reward_per_share / risk_per_share
        if reward_per_share <= 0:
            context["entry_approved"] = False
            context["rejection_reason"] = "invalid reward setup"
            return False, context

        context.update(
            {
                "reason": "opening range breakout above VWAP with volume confirmation",
                "strategy_name": self.name,
                "setup_type": "opening_range_vwap",
                "entry_price": entry_price,
                "stop_loss": stop_loss,
                "take_profit": take_profit,
                "stop_price": stop_loss,
                "target_price": take_profit,
                "risk_per_share": risk_per_share,
                "risk_reward": risk_reward,
            }
        )
        return True, context

    def build_signal_context(self, symbol: str, features: dict, regime: dict) -> dict:
        context = self._base_context(symbol, features, regime)
        rejection = self._entry_rejection(symbol, features, regime)
        if rejection is not None:
            context["entry_approved"] = False
            context["rejection_reason"] = rejection
            return context

        entry_price = float(features["close"])
        stop_loss = self._select_stop_loss(entry_price, features)
        if stop_loss is None:
            context["entry_approved"] = False
            context["rejection_reason"] = "no valid stop loss"
            return context

        risk_per_share = entry_price - stop_loss
        target_r = float(config.ORVWAP_TARGET_R)
        take_profit = entry_price + (risk_per_share * target_r)

        context.update(
            {
                "entry_approved": True,
                "rejection_reason": "",
                "entry_price": entry_price,
                "stop_price": stop_loss,
                "target_price": take_profit,
                "stop_loss": stop_loss,
                "take_profit": take_profit,
                "risk_per_share": risk_per_share,
                "target_r": target_r,
                "reason": "opening range breakout above VWAP with volume confirmation",
                "strategy_name": self.name,
                "setup_type": "opening_range_vwap",
                "risk_reward": (take_profit - entry_price) / risk_per_share,
            }
        )
        return context

    def evaluate_exit(
        self,
        position: dict,
        features: dict,
        regime: dict,
        holding_minutes: float,
        in_open_window: bool = False,
    ) -> tuple[bool, str]:
        close_price = float(features["close"])
        entry_price = float(position["entry_price"])
        stop_loss = float(position["stop_loss"])
        take_profit = float(position["take_profit"])
        risk_per_share = float(position.get("risk_per_share", entry_price - stop_loss))

        if close_price <= stop_loss:
            return True, "stop loss"

        if close_price >= take_profit:
            return True, f"{config.ORVWAP_TARGET_R}R take profit"

        if config.ORVWAP_USE_TRAILING_AFTER_1R:
            one_r_price = entry_price + risk_per_share
            if close_price >= one_r_price:
                trailing_stop = max(stop_loss, entry_price)
                if close_price <= trailing_stop:
                    return True, "trailing stop after 1R"

        if config.ORVWAP_EXIT_ON_VWAP_LOSS and not bool(features.get("above_vwap", False)):
            return True, "lost VWAP"

        if not in_open_window and holding_minutes >= float(config.MAX_HOLD_MINUTES):
            return True, "max hold time"

        return False, "hold"

    def holds_overnight(self) -> bool:
        return False

    def _base_context(self, symbol: str, features: dict, regime: dict) -> dict:
        return {
            "timestamp": features.get("timestamp"),
            "ticker": symbol,
            "mode": config.TRADING_MODE,
            "price": float(features.get("close", 0.0)),
            "opening_range_high": features.get("opening_range_high"),
            "opening_range_low": features.get("opening_range_low"),
            "vwap": features.get("vwap"),
            "current_volume": features.get("volume"),
            "volume_avg_20": features.get("volume_avg_20"),
            "volume_ratio": features.get("volume_ratio"),
            "atr": features.get("atr_14"),
            "distance_from_vwap": features.get("vwap_distance"),
            "distance_from_vwap_atr": features.get("distance_from_vwap_atr"),
            "spread": features.get("spread_percent"),
            "entry_approved": False,
            "rejection_reason": "",
            "entry_price": None,
            "stop_price": None,
            "target_price": None,
            "position_size": None,
            "exit_price": None,
            "exit_reason": None,
            "realized_pnl": None,
            "account_equity": None,
            "strategy_version": self.name,
            "spy_above_vwap": regime.get("spy_above_vwap"),
            "qqq_above_vwap": regime.get("qqq_above_vwap"),
            "market_filter_reason": regime.get("reason"),
        }

    def _entry_rejection(self, symbol: str, features: dict, regime: dict) -> str | None:
        if symbol not in self.UNIVERSE:
            return "symbol outside v1 universe"

        if not bool(features.get("in_entry_window", False)):
            return "outside entry window"

        if not bool(features.get("or_complete", False)):
            return "opening range not complete"

        if not self._passed_opening_range_breakout(features):
            return "no opening range breakout close"

        if not bool(features.get("above_vwap", False)):
            return "price below VWAP"

        if float(features.get("volume_ratio", 0.0)) < float(config.ORVWAP_MIN_VOLUME_RATIO):
            return "volume ratio too low"

        if float(features.get("spread_percent", 0.0)) > float(config.ORVWAP_MAX_SPREAD_PCT):
            return "spread too wide"

        distance_atr = features.get("distance_from_vwap_atr")
        if distance_atr is not None and float(distance_atr) > float(
            config.ORVWAP_MAX_VWAP_EXTENSION_ATR
        ):
            return "extended too far from VWAP"

        if not regime.get("trade_allowed", False):
            return regime.get("reason", "market filter blocked")

        if symbol in self.TECH_SYMBOLS and not regime.get("qqq_above_vwap", False):
            return "QQQ below VWAP for tech symbol"

        return None

    def _select_stop_loss(self, entry_price: float, features: dict) -> float | None:
        candidates = []

        vwap = features.get("vwap")
        if vwap is not None:
            candidates.append(float(vwap))

        or_mid = features.get("opening_range_midpoint")
        if or_mid is not None:
            candidates.append(float(or_mid))

        candidates.append(entry_price * (1.0 - float(config.ORVWAP_STOP_PCT)))

        atr = features.get("atr_14")
        if atr is not None:
            candidates.append(entry_price - (float(atr) * float(config.ORVWAP_ATR_STOP_MULTIPLE)))

        valid = [stop for stop in candidates if stop < entry_price]
        if not valid:
            return None

        if getattr(config, "ORVWAP_STOP_SELECTION", "tightest") == "widest":
            return min(valid)
        return max(valid)

    def _passed_opening_range_breakout(self, features: dict) -> bool:
        or_high = features.get("opening_range_high")
        close_price = features.get("close")
        if or_high is None or close_price is None:
            return bool(features.get("or_breakout_close", False))

        buffer_pct = float(config.ORVWAP_OR_BREAKOUT_BUFFER_PCT)
        threshold = float(or_high) * (1.0 - buffer_pct / 100.0)
        return float(close_price) > threshold
