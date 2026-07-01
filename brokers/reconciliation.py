from dataclasses import dataclass

from brokers.base import Position
from database.repositories import save_risk_event


@dataclass(frozen=True)
class ReconciliationResult:
    ok: bool
    missing_locally: list[str]
    missing_at_broker: list[str]
    quantity_mismatches: list[str]

    @property
    def issues(self) -> list[str]:
        return self.missing_locally + self.missing_at_broker + self.quantity_mismatches


def reconcile_positions(local_positions: list[dict], broker_positions: list[Position]) -> ReconciliationResult:
    local_by_symbol = {
        str(position["symbol"]): int(position["shares"])
        for position in local_positions
        if str(position.get("status", "OPEN")) == "OPEN"
    }
    broker_by_symbol = {
        position.symbol: int(position.quantity)
        for position in broker_positions
        if int(position.quantity) != 0
    }

    local_symbols = set(local_by_symbol)
    broker_symbols = set(broker_by_symbol)
    missing_locally = sorted(broker_symbols - local_symbols)
    missing_at_broker = sorted(local_symbols - broker_symbols)
    quantity_mismatches = sorted(
        symbol
        for symbol in local_symbols & broker_symbols
        if local_by_symbol[symbol] != broker_by_symbol[symbol]
    )

    result = ReconciliationResult(
        ok=not (missing_locally or missing_at_broker or quantity_mismatches),
        missing_locally=missing_locally,
        missing_at_broker=missing_at_broker,
        quantity_mismatches=quantity_mismatches,
    )
    if not result.ok:
        save_risk_event(
            "BROKER_RECONCILIATION_FAILED",
            "Local positions do not match broker positions.",
            severity="ERROR",
            payload={
                "missing_locally": missing_locally,
                "missing_at_broker": missing_at_broker,
                "quantity_mismatches": quantity_mismatches,
            },
        )
    return result
