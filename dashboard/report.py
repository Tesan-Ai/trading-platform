import config
from analytics.trade_analytics import print_report
from backtesting.profitability_replay import run_profitability_replay
from risk_manager import get_current_equity, get_tradable_equity, can_open_new_position


def print_dashboard(symbols=None) -> None:
    if symbols is None:
        symbols = [
            "AAPL", "MSFT", "NVDA", "AMD", "META",
            "TSLA", "AMZN", "PLTR", "SOFI", "RKLB"
        ]

    print("\nTRADING BOT DASHBOARD")
    print("---------------------")
    print(f"Mode:                  {config.TRADING_MODE}")
    print(f"Live enabled:          {config.LIVE_ENABLED}")
    print(f"Global kill switch:    {config.GLOBAL_KILL_SWITCH}")
    print(f"Strategy:              {config.STRATEGY_NAME}")
    print(f"PDT floor:             ${config.DO_NOT_TRADE_BELOW_EQUITY:,.2f}")
    print(f"Current equity:        ${get_current_equity():,.2f}")
    print(f"Tradable cushion:      ${get_tradable_equity():,.2f}")
    print(f"Can open now:          {can_open_new_position(0)}")
    print(f"Max daily loss:        ${config.MAX_DAILY_LOSS_DOLLARS:,.2f}")
    print(f"Max drawdown:          {config.MAX_DRAWDOWN_PERCENT * 100:.2f}%")
    print(f"Max trades/day:        {config.MAX_TRADES_PER_DAY}")

    result = run_profitability_replay(
        symbols=symbols,
        data_dir="historical_data",
        starting_cash=100000.0
    )

    print(f"Latest replay regime:  {result['latest_regime'].get('regime')}")
    print_report(result["report"])

    gate = validate_paper_gate(result["report"])
    print("\nPAPER -> LIVE GATE")
    print("------------------")
    print(f"Passes gate:           {gate['passes']}")
    for reason in gate["reasons"]:
        print(f"- {reason}")


def validate_paper_gate(report: dict) -> dict:
    reasons = []

    if report.get("closed_trades", 0) < config.MIN_PAPER_TRADES_BEFORE_LIVE:
        reasons.append("not enough paper trades")

    if report.get("expectancy", 0.0) <= config.MIN_EXPECTANCY_BEFORE_LIVE:
        reasons.append("expectancy is not positive")

    if report.get("profit_factor", 0.0) < config.MIN_PROFIT_FACTOR_BEFORE_LIVE:
        reasons.append("profit factor below live threshold")

    if report.get("max_drawdown", 1.0) > config.MAX_VALIDATED_DRAWDOWN:
        reasons.append("drawdown above validation threshold")

    return {
        "passes": not reasons,
        "reasons": reasons or ["paper-trading gate conditions satisfied"]
    }
