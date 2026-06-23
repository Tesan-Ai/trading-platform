from alpaca.data.historical import StockHistoricalDataClient
import config

client = StockHistoricalDataClient(
    config.ALPACA_API_KEY,
    config.ALPACA_SECRET_KEY
)

print("Connected to Alpaca successfully")
