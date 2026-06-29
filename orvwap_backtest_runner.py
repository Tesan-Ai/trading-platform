import argparse
import os

import config
from analytics.orvwap_report import build_orvwap_report, print_orvwap_report, save_orvwap_report
from backtesting.profitability_replay import run_profitability_replay
from signal_logger import ensure_signal_log_file, summarize_rejections
from strategies.factory import get_strategy


def resolve_symbols() -> list[str]:
    configured = list(getattr(config, "TRADE_SYMBOLS", []))
    if configured:
        return configured
    return list(getattr(config, "ORVWAP_TRADE_SYMBOLS", config.ORVWAP_UNIVERSE))


def main() -> None:
    parser = argparse.ArgumentParser(description="Backtest opening_range_vwap_momentum_v1")
    parser.add_argument("--start-date", default="2025-09-03")
    parser.add_argument("--end-date", default="2026-06-03")
    parser.add_argument("--capital", type=float, default=float(config.INITIAL_CAPITAL))
    parser.add_argument("--data-dir", default="historical_data")
    parser.add_argument("--target-r", type=float, default=float(config.ORVWAP_TARGET_R))
    parser.add_argument(
        "--trailing-after-1r",
        action="store_true",
        default=bool(config.ORVWAP_USE_TRAILING_AFTER_1R),
    )
    parser.add_argument("--output-dir", default=config.ORVWAP_REPORT_DIR)
    parser.add_argument(
        "--relaxed",
        action="store_true",
        help="Use near-miss test profile: vol 1.2, OR buffer 0.05%%, VWAP extension 2.0 ATR",
    )
    args = parser.parse_args()

    config.ACTIVE_STRATEGY = config.ORVWAP_STRATEGY_NAME
    config.ORVWAP_TARGET_R = args.target_r
    config.ORVWAP_USE_TRAILING_AFTER_1R = args.trailing_after_1r
    if args.relaxed:
        config.ORVWAP_MIN_VOLUME_RATIO = 1.2
        config.ORVWAP_OR_BREAKOUT_BUFFER_PCT = 0.05
        config.ORVWAP_MAX_VWAP_EXTENSION_ATR = 2.0
    config.TRADE_SYMBOLS = resolve_symbols()

    signal_log = ensure_signal_log_file()
    if os.path.exists(signal_log):
        os.remove(signal_log)
    ensure_signal_log_file()

    config.TRADE_SYMBOLS = resolve_symbols()
    data_symbols = list(
        dict.fromkeys(
            config.TRADE_SYMBOLS
            + [config.ORVWAP_MARKET_FILTER_SYMBOL, config.ORVWAP_TECH_FILTER_SYMBOL]
        )
    )

    strategy = get_strategy()
    result = run_profitability_replay(
        symbols=data_symbols,
        data_dir=args.data_dir,
        starting_cash=args.capital,
        start_date=args.start_date,
        end_date=args.end_date,
        strategy=strategy,
    )

    portfolio = result["portfolio"]
    equity_curve = portfolio.equity_curve
    rejection_counts = summarize_rejections(signal_log)
    report = build_orvwap_report(
        result["trade_rows"],
        equity_curve,
        signal_rows=result.get("signal_rows"),
        rejection_counts=rejection_counts,
    )

    print("\nOpening Range VWAP Momentum v1 backtest")
    if args.relaxed:
        print("Profile: RELAXED TEST (vol 1.2, OR buffer 0.05%, VWAP ext 2.0 ATR)")
    print(f"Symbols: {', '.join(config.TRADE_SYMBOLS)}")
    print(f"Window:  {args.start_date} -> {args.end_date}")
    print(f"Target:  {args.target_r}R")
    if equity_curve:
        starting_equity = float(equity_curve[0]["equity"])
        ending_equity = float(equity_curve[-1]["equity"])
        print(f"Starting equity: ${starting_equity:,.2f}")
        print(f"Ending equity:   ${ending_equity:,.2f}")
        print(f"Total return:    {((ending_equity - starting_equity) / starting_equity) * 100:.2f}%")

    print_orvwap_report(report)
    report_path = save_orvwap_report(report, args.output_dir)
    print(f"\nReport saved to: {report_path}")
    print(f"Signal log saved to: {signal_log}")


if __name__ == "__main__":
    main()
