from analytics.trade_analytics import print_report
from backtesting.profitability_replay import run_profitability_replay
import config


if __name__ == "__main__":
    symbols = list(config.TRADE_SYMBOLS)

    result = run_profitability_replay(
        symbols=symbols,
        data_dir="historical_data",
        starting_cash=float(config.INITIAL_CAPITAL),
        start_date="2025-09-03",
        end_date="2026-06-03",
    )

    portfolio = result["portfolio"]
    equity_curve = portfolio.equity_curve

    if equity_curve:
        starting_equity = float(equity_curve[0]["equity"])
        ending_equity = float(equity_curve[-1]["equity"])
        print("\nProfitability-first replay complete")
        print(f"Starting equity: ${starting_equity:,.2f}")
        print(f"Ending equity:   ${ending_equity:,.2f}")
        print(f"Total return:    {((ending_equity - starting_equity) / starting_equity) * 100:.2f}%")
        print(f"Latest regime:   {result['latest_regime'].get('regime')}")

    print_report(result["report"])
