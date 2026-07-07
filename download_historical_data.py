import argparse

from historical_data import fetch_and_save_bars
from watchlist import ETF_RESEARCH_UNIVERSE, WATCHLIST


DEFAULT_MARKET_SYMBOLS = ["SPY", "QQQ"]


def chunk_symbols(symbols, chunk_size):
    for index in range(0, len(symbols), chunk_size):
        yield symbols[index:index + chunk_size]


def parse_symbols(raw_symbols, include_watchlist, include_market):
    symbols = []

    if include_watchlist:
        symbols.extend(WATCHLIST)

    if raw_symbols:
        symbols.extend([symbol.strip().upper() for symbol in raw_symbols.split(",") if symbol.strip()])

    if include_market:
        symbols.extend(DEFAULT_MARKET_SYMBOLS)

    deduped = []
    seen = set()
    for symbol in symbols:
        if symbol not in seen:
            deduped.append(symbol)
            seen.add(symbol)

    return deduped


def parse_universe(universe):
    if universe == "etf":
        return ETF_RESEARCH_UNIVERSE

    if universe == "legacy":
        return WATCHLIST

    return []


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--end-date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--symbols", default="", help="Comma-separated symbols")
    parser.add_argument("--include-watchlist", action="store_true")
    parser.add_argument("--include-market", action="store_true")
    parser.add_argument("--universe", choices=["none", "etf", "legacy"], default="none")
    parser.add_argument("--output-dir", default="historical_data")
    parser.add_argument("--feed", default="sip")
    parser.add_argument("--batch-size", type=int, default=50)
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    symbols = parse_universe(args.universe)
    symbols.extend(parse_symbols(args.symbols, args.include_watchlist, args.include_market))

    symbols = list(dict.fromkeys(symbols))

    if not symbols:
        raise SystemExit("No symbols supplied.")

    print(f"Downloading {len(symbols)} symbols from {args.start_date} to {args.end_date}")
    print(f"Output directory: {args.output_dir}")

    for batch in chunk_symbols(symbols, args.batch_size):
        print(f"Downloading batch: {', '.join(batch)}")
        fetch_and_save_bars(
            symbols=batch,
            start_date=args.start_date,
            end_date=args.end_date,
            output_dir=args.output_dir,
            feed=args.feed
        )
