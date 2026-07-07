MARKET_ETFS = [
    "SPY",
    "QQQ"
]


SECTOR_ETFS = [
    "XLC",
    "XLY",
    "XLP",
    "XLE",
    "XLF",
    "XLV",
    "XLI",
    "XLB",
    "XLRE",
    "XLK",
    "XLU"
]


FACTOR_ETFS = [
    "MTUM",
    "QUAL",
    "VLUE",
    "USMV",
    "SIZE"
]


ETF_RESEARCH_UNIVERSE = MARKET_ETFS + SECTOR_ETFS + FACTOR_ETFS


LEGACY_WATCHLIST = [
    "ASTS",
    "AUR",
    "B",
    "AAPL",
    "MSFT",
    "O",
    "XOM",
    "KO",
    "CABA",
    "CEG",
    "CIFR",
    "CRWD",
    "EDSA",
    "ETHE",
    "FTNT",
    "GBTC",
    "ITA",
    "JOBY",
    "LLY",
    "MP",
    "NFLX",
    "NVDA",
    "OKLO",
    "ORCL",
    "PPA",
    "PWR",
    "QQQ",
    "QQQI",
    "RGTI",
    "RKLB",
    "RIVN",
    "SONY",
    "SPYM",
    "TBBK",
    "UEC",
    "XLK",
    "AMZN",
    "META",
    "AVGO",
    "ONDS",
    "SOFI",
    "F",
    "MU",
    "BMNR",
    "INTC",
    "AMD"
]


WATCHLIST = ETF_RESEARCH_UNIVERSE


# Liquid US equities for "stocks in play" daily scanner (research mode).
# Backtests skip symbols without a CSV in historical_data/.
SCANNER_UNIVERSE = [
    "AAPL", "MSFT", "AMZN", "NVDA", "GOOGL", "GOOG", "META", "TSLA", "BRK.B", "UNH",
    "JPM", "V", "XOM", "LLY", "JNJ", "WMT", "MA", "PG", "AVGO", "HD",
    "CVX", "MRK", "COST", "ABBV", "PEP", "KO", "ADBE", "CRM", "MCD", "CSCO",
    "ACN", "TMO", "NFLX", "AMD", "LIN", "ABT", "DHR", "WFC", "DIS", "VZ",
    "INTC", "CMCSA", "TXN", "PM", "NEE", "COP", "ORCL", "QCOM", "IBM", "AMAT",
    "CAT", "GE", "UNP", "HON", "LOW", "BA", "SBUX", "GS", "MS", "BLK",
    "ISRG", "PLTR", "SOFI", "COIN", "HOOD", "RIVN", "LCID", "NIO", "BABA", "PDD",
    "MU", "LRCX", "KLAC", "SNPS", "CDNS", "PANW", "CRWD", "FTNT", "NOW", "SNOW",
    "UBER", "LYFT", "ABNB", "DASH", "SQ", "PYPL", "SHOP", "MELI", "SE", "NET",
    "SMCI", "ARM", "MRVL", "ON", "TSM", "ASML", "DE", "RTX", "LMT", "NKE",
]
