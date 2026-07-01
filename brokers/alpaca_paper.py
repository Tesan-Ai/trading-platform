import config
from brokers.base import Broker, OrderRequest, OrderResult, Position
from database.repositories import save_order, save_positions


class AlpacaPaperBroker(Broker):
    name = "alpaca_paper"

    def __init__(self):
        if not config.ALPACA_API_KEY or not config.ALPACA_SECRET_KEY:
            raise RuntimeError("Set ALPACA_API_KEY and ALPACA_SECRET_KEY in .env")

        from alpaca.trading.client import TradingClient

        self.client = TradingClient(
            api_key=config.ALPACA_API_KEY,
            secret_key=config.ALPACA_SECRET_KEY,
            paper=True,
        )

    def get_positions(self) -> list[Position]:
        positions = []
        for item in self.client.get_all_positions():
            positions.append(
                Position(
                    symbol=item.symbol,
                    quantity=int(float(item.qty)),
                    average_entry_price=float(item.avg_entry_price),
                    market_value=float(item.market_value) if item.market_value is not None else None,
                )
            )
        save_positions(self.name, [position.__dict__ for position in positions])
        return positions

    def submit_order(self, order: OrderRequest) -> OrderResult:
        from alpaca.trading.enums import OrderSide, TimeInForce
        from alpaca.trading.requests import MarketOrderRequest

        request = MarketOrderRequest(
            symbol=order.symbol,
            qty=order.quantity,
            side=OrderSide.BUY if order.side.lower() == "buy" else OrderSide.SELL,
            time_in_force=TimeInForce.DAY,
        )
        response = self.client.submit_order(order_data=request)
        result = _order_result(response, order)
        save_order(
            {
                "broker": self.name,
                "broker_order_id": result.broker_order_id,
                "strategy": config.ACTIVE_STRATEGY,
                "symbol": result.symbol,
                "side": result.side,
                "quantity": result.quantity,
                "order_type": order.order_type,
                "time_in_force": order.time_in_force,
                "status": result.status,
                "filled_price": result.filled_price,
                "payload": _payload_from_order(response),
            }
        )
        return result

    def close_position(self, symbol: str) -> OrderResult:
        response = self.client.close_position(symbol)
        result = OrderResult(
            broker_order_id=str(getattr(response, "id", "")),
            symbol=symbol,
            side="sell",
            quantity=int(float(getattr(response, "qty", 0) or 0)),
            status=str(getattr(response, "status", "submitted")),
            filled_price=_float_or_none(getattr(response, "filled_avg_price", None)),
        )
        save_order(
            {
                "broker": self.name,
                "broker_order_id": result.broker_order_id,
                "strategy": config.ACTIVE_STRATEGY,
                "symbol": result.symbol,
                "side": result.side,
                "quantity": result.quantity,
                "order_type": "market",
                "time_in_force": "day",
                "status": result.status,
                "filled_price": result.filled_price,
                "payload": _payload_from_order(response),
            }
        )
        return result


def _order_result(response, request: OrderRequest) -> OrderResult:
    return OrderResult(
        broker_order_id=str(getattr(response, "id", "")),
        symbol=getattr(response, "symbol", request.symbol),
        side=str(getattr(response, "side", request.side)),
        quantity=int(float(getattr(response, "qty", request.quantity) or request.quantity)),
        status=str(getattr(response, "status", "submitted")),
        filled_price=_float_or_none(getattr(response, "filled_avg_price", None)),
    )


def _payload_from_order(response) -> dict:
    if hasattr(response, "model_dump"):
        return response.model_dump(mode="json")
    if hasattr(response, "dict"):
        return response.dict()
    return {"repr": repr(response)}


def _float_or_none(value) -> float | None:
    if value in {None, ""}:
        return None
    return float(value)
