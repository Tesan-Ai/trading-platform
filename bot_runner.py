from datetime import datetime
from zoneinfo import ZoneInfo

import config
from paper_trader import run_paper_trading_cycle
from trader import run_trading_day

EASTERN = ZoneInfo("America/New_York")


def run_trading_cycle(current_time=None, current_pnl=0.0):
    if config.ACTIVE_STRATEGY == "daily_trend_v1":
        return run_paper_trading_cycle(current_time=current_time)

    if current_time is None:
        current_time = datetime.now(EASTERN)

    return run_trading_day(current_time=current_time, current_pnl=current_pnl)
