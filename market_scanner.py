import math
from typing import List, Dict, Any, Optional

import pandas as pd
from alpaca.trading.client import TradingClient
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockSnapshotRequest, StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import config
from ai_model import score_data_frame, get_daily_trend_metrics

EASTERN = ZoneInfo("America/New_York")

trading_client = None
data_client = None


def require_alpaca_credentials() -> None:
    if not config.ALPACA_API_KEY or not config.ALPACA_SECRET_KEY:
        raise RuntimeError("Set ALPACA_API_KEY and ALPACA_SECRET_KEY in .env")


def get_trading_client() -> TradingClient:
    global trading_client

    if trading_client is not None:
        return trading_client

    require_alpaca_credentials()
    trading_client = TradingClient(
        api_key=config.ALPACA_API_KEY,
        secret_key=config.ALPACA_SECRET_KEY,
        paper=True
    )
    return trading_client


def get_data_client() -> StockHistoricalDataClient:
    global data_client

    if data_client is not None:
        return data_client

    require_alpaca_credentials()
    data_client = StockHistoricalDataClient(
        api_key=config.ALPACA_API_KEY,
        secret_key=config.ALPACA_SECRET_KEY
    )
    return data_client


def chunk_symbols(symbols: List[str], chunk_size: int) -> List[List[str]]:
    chunks = []

    for index in range(0, len(symbols), chunk_size):
        chunks.append(symbols[index:index + chunk_size])

    return chunks


def normalize_time(current_time: Optional[datetime]) -> datetime:
    if current_time is None:
        return datetime.now(EASTERN)

    if current_time.tzinfo is None:
        return current_time.replace(tzinfo=EASTERN)

    return current_time.astimezone(EASTERN)


def get_tradable_symbols() -> List[str]:
    assets = get_trading_client().get_all_assets()
    symbols = []

    for asset in assets:
        if not asset.tradable:
            continue

        if asset.asset_class != "us_equity":
            continue

        if asset.status != "active":
            continue

        symbol = asset.symbol

        if symbol in getattr(config, "SYMBOL_BLACKLIST", set()):
            continue

        if "." in symbol or "/" in symbol or "-" in symbol:
            continue

        symbols.append(symbol)

    return symbols


def score_snapshot(symbol: str, snapshot: Any) -> Optional[Dict[str, Any]]:
    if snapshot is None:
        return None

    daily_bar = snapshot.daily_bar
    prev_daily_bar = snapshot.previous_daily_bar
    latest_trade = snapshot.latest_trade
    latest_quote = snapshot.latest_quote
    minute_bar = snapshot.minute_bar

    if daily_bar is None or prev_daily_bar is None:
        return None

    current_price = None

    if latest_trade is not None and latest_trade.price is not None:
        current_price = float(latest_trade.price)
    elif minute_bar is not None and minute_bar.close is not None:
        current_price = float(minute_bar.close)
    elif daily_bar.close is not None:
        current_price = float(daily_bar.close)

    if current_price is None or current_price <= 0:
        return None

    prev_close = float(prev_daily_bar.close)

    if prev_close <= 0:
        return None

    day_volume = float(daily_bar.volume or 0)

    if current_price < config.MIN_PRICE:
        return None

    if current_price > config.MAX_PRICE:
        return None

    if day_volume < config.MIN_DAILY_VOLUME:
        return None

    percent_change = ((current_price - prev_close) / prev_close) * 100.0

    if percent_change < getattr(config, "MIN_ABS_PERCENT_CHANGE", 0.0):
        return None

    spread_percent = 0.0

    if (
        latest_quote is not None
        and latest_quote.ask_price is not None
        and latest_quote.bid_price is not None
    ):
        ask_price = float(latest_quote.ask_price)
        bid_price = float(latest_quote.bid_price)

        if ask_price > 0 and bid_price > 0 and current_price > 0:
            spread_percent = ((ask_price - bid_price) / current_price) * 100.0

    if spread_percent > config.MAX_SPREAD_PERCENT:
        return None

    liquidity_score = min(10.0, math.log10(max(day_volume, 1)) * 1.5)
    momentum_score = max(0.0, percent_change)
    spread_penalty = spread_percent

    total_score = (
        getattr(config, "WEIGHT_MOMENTUM", 0.8) * momentum_score
        + getattr(config, "WEIGHT_LIQUIDITY", 1.0) * liquidity_score
        - getattr(config, "WEIGHT_SPREAD", 1.0) * spread_penalty
    )

    return {
        "symbol": symbol,
        "price": current_price,
        "percent_change": percent_change,
        "day_volume": day_volume,
        "spread_percent": spread_percent,
        "scan_score": round(total_score, 4)
    }


def fetch_intraday_bars_for_symbols(
    symbols: List[str],
    minutes_back: int = 120,
    current_time: Optional[datetime] = None
) -> Dict[str, pd.DataFrame]:
    if not symbols:
        return {}

    end_time = normalize_time(current_time)
    start_time = end_time - timedelta(minutes=minutes_back)

    request = StockBarsRequest(
        symbol_or_symbols=symbols,
        timeframe=TimeFrame.Minute,
        start=start_time,
        end=end_time,
        feed=config.ALPACA_DATA_FEED,
    )

    try:
        bars_response = get_data_client().get_stock_bars(request)
    except Exception as error:
        print(f"Intraday bars request failed: {error}")
        return {}

    bars_by_symbol: Dict[str, pd.DataFrame] = {}

    for symbol in symbols:
        if symbol not in bars_response.data:
            continue

        bars = bars_response.data[symbol]

        if not bars:
            continue

        rows = []

        for bar in bars:
            rows.append({
                "timestamp": bar.timestamp,
                "open": float(bar.open),
                "high": float(bar.high),
                "low": float(bar.low),
                "close": float(bar.close),
                "volume": float(bar.volume)
            })

        if not rows:
            continue

        data_frame = pd.DataFrame(rows)
        data_frame = data_frame.sort_values("timestamp").reset_index(drop=True)

        if not data_frame.empty:
            bars_by_symbol[symbol] = data_frame

    return bars_by_symbol


def scan_market(current_time: Optional[datetime] = None) -> List[Dict[str, Any]]:
    symbols = get_tradable_symbols()

    print(f"Tradable symbols found: {len(symbols)}")

    if config.MAX_SYMBOLS_TO_SCAN > 0:
        symbols = symbols[:config.MAX_SYMBOLS_TO_SCAN]
        print(f"Symbols after MAX_SYMBOLS_TO_SCAN cap: {len(symbols)}")
    else:
        print("Scanning full tradable universe.")

    snapshot_candidates: List[Dict[str, Any]] = []
    symbol_batches = chunk_symbols(symbols, 200)

    print(f"Snapshot request batches: {len(symbol_batches)}")

    for batch_index, batch in enumerate(symbol_batches, start=1):
        try:
            request = StockSnapshotRequest(symbol_or_symbols=batch)
            snapshots = get_data_client().get_stock_snapshot(request)

            for symbol, snapshot in snapshots.items():
                scored = score_snapshot(symbol, snapshot)

                if scored is not None:
                    snapshot_candidates.append(scored)

        except Exception as error:
            print(f"Snapshot batch {batch_index} failed: {error}")

    print(f"Candidates after snapshot filters: {len(snapshot_candidates)}")

    if not snapshot_candidates:
        return []

    snapshot_candidates.sort(key=lambda item: item["scan_score"], reverse=True)

    snapshot_pool_size = getattr(
        config,
        "SNAPSHOT_POOL_SIZE",
        max(config.MAX_DEEP_SCORE_CANDIDATES * 2, config.TOP_CANDIDATES_TO_TRADE)
    )

    snapshot_candidates = snapshot_candidates[:snapshot_pool_size]

    print(f"Candidates kept after snapshot ranking: {len(snapshot_candidates)}")

    deep_score_count = config.MAX_DEEP_SCORE_CANDIDATES

    if deep_score_count > 0:
        deep_score_candidates = snapshot_candidates[:deep_score_count]
    else:
        deep_score_candidates = snapshot_candidates

    shortlisted_symbols = [item["symbol"] for item in deep_score_candidates]

    print(f"Symbols moving to deep scoring: {len(shortlisted_symbols)}")

    if not shortlisted_symbols:
        return []

    scored_candidates: List[Dict[str, Any]] = []
    intraday_batches = chunk_symbols(shortlisted_symbols, 100)

    snapshot_lookup = {}
    for candidate in deep_score_candidates:
        snapshot_lookup[candidate["symbol"]] = candidate

    intraday_minutes_back = getattr(config, "INTRADAY_MINUTES_BACK", 120)
    weight_snapshot_score = getattr(config, "WEIGHT_SNAPSHOT_SCORE", 0.15)
    weight_intraday_score = getattr(config, "WEIGHT_INTRADAY_SCORE", 0.85)

    for batch_index, batch in enumerate(intraday_batches, start=1):
        try:
            bars_by_symbol = fetch_intraday_bars_for_symbols(
                symbols=batch,
                minutes_back=intraday_minutes_back,
                current_time=current_time
            )

            for symbol in batch:
                if symbol not in bars_by_symbol:
                    continue

                candidate = snapshot_lookup.get(symbol)
                if candidate is None:
                    continue

                daily_trend = get_daily_trend_metrics(symbol, current_time=current_time)

                if daily_trend is None or not daily_trend["is_uptrend"]:
                    continue

                intraday_score = score_data_frame(
                    symbol,
                    bars_by_symbol[symbol],
                    daily_trend
                )

                if intraday_score is None:
                    continue

                if intraday_score["score"] < getattr(config, "MIN_INTRADAY_SCORE", 0.0):
                    continue

                combined_score = (
                    weight_snapshot_score * candidate["scan_score"]
                    + weight_intraday_score * intraday_score["score"]
                )

                scored_candidates.append({
                    "symbol": symbol,
                    "price": intraday_score["close"],
                    "percent_change": candidate["percent_change"],
                    "day_volume": candidate["day_volume"],
                    "spread_percent": candidate["spread_percent"],
                    "scan_score": round(candidate["scan_score"], 2),
                    "intraday_score": intraday_score["score"],
                    "score": round(combined_score, 2),
                    "return_3m": intraday_score["return_3m"],
                    "return_5m": intraday_score["return_5m"],
                    "return_15m": intraday_score["return_15m"],
                    "return_30m": intraday_score["return_30m"],
                    "ema_ratio": intraday_score["ema_ratio"],
                    "relative_volume": intraday_score["relative_volume"],
                    "vwap_distance": intraday_score["vwap_distance"],
                    "pullback_position": intraday_score["pullback_position"],
                    "bar_range_percent": intraday_score["bar_range_percent"],
                    "distance_to_ma50": intraday_score["distance_to_ma50"],
                    "daily_ma50": intraday_score["daily_ma50"],
                    "daily_ma200": intraday_score["daily_ma200"]
                })

        except Exception as error:
            print(f"Deep scoring batch {batch_index} failed: {error}")

    print(f"Candidates after deep scoring: {len(scored_candidates)}")

    if not scored_candidates:
        return []

    scored_candidates.sort(key=lambda item: item["score"], reverse=True)

    top_count = config.TOP_CANDIDATES_TO_TRADE
    if top_count > 0:
        scored_candidates = scored_candidates[:top_count]

    print(f"Candidates returned to trader: {len(scored_candidates)}")

    if scored_candidates:
        print("Top 10 scored candidates:")
        for candidate in scored_candidates[:10]:
            print(
                f'{candidate["symbol"]} | '
                f'Score={candidate["score"]:.2f} | '
                f'Snapshot={candidate["scan_score"]:.2f} | '
                f'Intraday={candidate["intraday_score"]:.2f} | '
                f'%Chg={candidate["percent_change"]:.2f} | '
                f'3m={candidate["return_3m"]:.4f} | '
                f'5m={candidate["return_5m"]:.4f} | '
                f'15m={candidate["return_15m"]:.4f} | '
                f'RVOL={candidate["relative_volume"]:.2f} | '
                f'EMA={candidate["ema_ratio"]:.4f} | '
                f'VWAPDist={candidate["vwap_distance"]:.4f} | '
                f'PullbackPos={candidate["pullback_position"]:.4f} | '
                f'DistTo50={candidate["distance_to_ma50"]:.4f}'
            )

    return scored_candidates
