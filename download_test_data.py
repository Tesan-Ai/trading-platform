from historical_data import fetch_and_save_bars

symbols = [
    "AAPL", "MSFT", "NVDA", "AMD", "META",
    "TSLA", "AMZN", "PLTR", "SOFI", "RKLB"
]

fetch_and_save_bars(
    symbols=symbols,
    start_date="2026-03-10",
    end_date="2026-03-14",
    output_dir="historical_data"
)
