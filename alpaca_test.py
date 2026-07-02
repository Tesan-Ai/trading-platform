from alpaca.data.historical import StockHistoricalDataClient
import config


def main():
    if not config.ALPACA_API_KEY or not config.ALPACA_SECRET_KEY:
        raise RuntimeError("Set ALPACA_API_KEY and ALPACA_SECRET_KEY before testing Alpaca.")

    StockHistoricalDataClient(
        config.ALPACA_API_KEY,
        config.ALPACA_SECRET_KEY,
    )
    print("Connected to Alpaca successfully")


if __name__ == "__main__":
    main()
