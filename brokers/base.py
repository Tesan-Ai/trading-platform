from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class OrderRequest:
    symbol: str
    side: str
    quantity: int
    order_type: str = "market"
    time_in_force: str = "day"


@dataclass(frozen=True)
class OrderResult:
    broker_order_id: str
    symbol: str
    side: str
    quantity: int
    status: str
    filled_price: float | None = None


@dataclass(frozen=True)
class Position:
    symbol: str
    quantity: int
    average_entry_price: float
    market_value: float | None = None


class Broker(Protocol):
    def get_positions(self) -> list[Position]:
        raise NotImplementedError

    def submit_order(self, order: OrderRequest) -> OrderResult:
        raise NotImplementedError

    def close_position(self, symbol: str) -> OrderResult:
        raise NotImplementedError
