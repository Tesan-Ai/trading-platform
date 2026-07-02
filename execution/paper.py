from datetime import datetime

import config
from database import get_observability_store
from portfolio_manager import add_position, close_position


class PaperExecutionEngine:
    def __init__(self, bot_run_id: int | None = None):
        self.bot_run_id = bot_run_id
        self.store = get_observability_store()

    def _ensure_paper(self) -> None:
        if config.TRADING_MODE != "PAPER":
            message = f"paper execution rejected non-paper mode: {config.TRADING_MODE}"
            self.store.log_risk_event(
                self.bot_run_id,
                message,
                severity="critical",
                event_type="paper_only_violation",
                blocked_trade=True,
                rule_name="paper_only",
            )
            raise RuntimeError(message)

    def buy(self, symbol: str, signal: dict, quantity: int, current_time: datetime) -> dict:
        self._ensure_paper()
        add_position(symbol=symbol, entry_price=signal["entry_price"], shares=quantity, entry_score=0.0, current_time=current_time)
        order = {
            "symbol": symbol,
            "side": "buy",
            "quantity": quantity,
            "entry_price": float(signal["entry_price"]),
            "stop_loss": float(signal["stop_price"]),
            "take_profit": float(signal["target_price"]),
            "risk_reward": signal.get("risk_reward"),
            "order_status": "paper_filled",
            "broker_order_id": f"paper-{symbol}-{int(current_time.timestamp())}",
            "strategy_name": config.ACTIVE_STRATEGY,
            "trading_mode": config.TRADING_MODE,
            "entry_reason": signal.get("reason"),
            "opened_at": current_time.isoformat(),
            "is_open": True,
        }
        self.store.log_trade(self.bot_run_id, order)
        self.store.upsert_position(
            {
                "symbol": symbol,
                "quantity": quantity,
                "average_price": float(signal["entry_price"]),
                "current_price": float(signal["entry_price"]),
                "unrealized_pnl": 0.0,
                "strategy_name": config.ACTIVE_STRATEGY,
                "trading_mode": config.TRADING_MODE,
                "opened_at": current_time.isoformat(),
            }
        )
        return order

    def sell(self, position: dict, exit_price: float, reason: str, current_time: datetime) -> dict:
        self._ensure_paper()
        symbol = position["symbol"]
        close_position(symbol)
        quantity = int(position["shares"])
        entry_price = float(position["entry_price"])
        pnl = round((float(exit_price) - entry_price) * quantity, 2)
        order = {
            "symbol": symbol,
            "side": "sell",
            "quantity": quantity,
            "entry_price": entry_price,
            "exit_price": float(exit_price),
            "realized_pnl": pnl,
            "order_status": "paper_filled",
            "broker_order_id": f"paper-{symbol}-exit-{int(current_time.timestamp())}",
            "strategy_name": config.ACTIVE_STRATEGY,
            "trading_mode": config.TRADING_MODE,
            "exit_reason": reason,
            "closed_at": current_time.isoformat(),
            "is_open": False,
        }
        self.store.log_trade(self.bot_run_id, order)
        self.store.close_position(symbol)
        return order
