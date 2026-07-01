import config
from brokers.base import Broker


def get_broker(provider: str | None = None) -> Broker | None:
    broker_provider = provider or getattr(config, "BROKER_PROVIDER", "csv")
    if broker_provider == "alpaca_paper":
        from brokers.alpaca_paper import AlpacaPaperBroker

        return AlpacaPaperBroker()
    if broker_provider == "csv":
        return None
    raise ValueError(f"Unknown broker provider: {broker_provider}")
