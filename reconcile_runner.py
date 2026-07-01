from brokers.factory import get_broker
from brokers.reconciliation import reconcile_positions
from monitoring.sentry_setup import init_sentry
from portfolio_manager import load_open_positions


def main() -> None:
    init_sentry()
    broker = get_broker()
    if broker is None:
        print("BROKER_PROVIDER=csv; no external broker reconciliation required.")
        return

    result = reconcile_positions(load_open_positions(), broker.get_positions())
    print("BROKER RECONCILIATION")
    print("---------------------")
    print(f"OK: {result.ok}")
    if result.missing_locally:
        print(f"Missing locally:       {', '.join(result.missing_locally)}")
    if result.missing_at_broker:
        print(f"Missing at broker:     {', '.join(result.missing_at_broker)}")
    if result.quantity_mismatches:
        print(f"Quantity mismatches:   {', '.join(result.quantity_mismatches)}")


if __name__ == "__main__":
    main()
