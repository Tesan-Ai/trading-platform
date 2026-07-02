import json
import os
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

import config

EASTERN = ZoneInfo("America/New_York")
DEFAULT_DB_PATH = os.getenv("BOT_DB_PATH", "data/trading_bot.sqlite3")


def _now_iso() -> str:
    return datetime.now(EASTERN).isoformat()


def _json(data) -> str | None:
    if data is None:
        return None
    return json.dumps(data, default=str, sort_keys=True)


def _bool(value) -> int:
    return 1 if bool(value) else 0


class ObservabilityStore:
    """Small durable store used locally and shaped to match the Supabase schema."""

    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        self.db_path = db_path
        directory = os.path.dirname(db_path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        self._init_schema()

    def connect(self):
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _init_schema(self) -> None:
        with self.connect() as connection:
            connection.executescript(
                """
                create table if not exists bot_runs (
                    id integer primary key autoincrement,
                    started_at text not null,
                    stopped_at text,
                    status text not null,
                    strategy_name text not null,
                    trading_mode text not null,
                    active_symbols text,
                    error_message text,
                    latest_heartbeat_at text
                );
                create table if not exists bot_heartbeats (
                    id integer primary key autoincrement,
                    bot_run_id integer,
                    timestamp text not null,
                    status text not null,
                    current_loop_state text,
                    active_strategy text,
                    trading_mode text
                );
                create table if not exists signals (
                    id integer primary key autoincrement,
                    bot_run_id integer,
                    timestamp text not null,
                    symbol text,
                    strategy_name text,
                    signal_type text,
                    confidence real,
                    price real,
                    opening_range_high real,
                    opening_range_low real,
                    opening_range_midpoint real,
                    vwap real,
                    atr real,
                    volume_ratio real,
                    spread_percentage real,
                    market_filter_allowed integer,
                    market_filter_reason text,
                    passed_entry_rules integer,
                    trade_executed integer,
                    reason text,
                    skip_reason text,
                    raw_data_json text
                );
                create table if not exists trades (
                    id integer primary key autoincrement,
                    bot_run_id integer,
                    timestamp text not null,
                    symbol text not null,
                    side text not null,
                    quantity integer,
                    entry_price real,
                    exit_price real,
                    stop_loss real,
                    take_profit real,
                    realized_pnl real,
                    unrealized_pnl real,
                    risk_reward real,
                    order_status text,
                    broker_order_id text,
                    strategy_name text,
                    trading_mode text,
                    entry_reason text,
                    exit_reason text,
                    opened_at text,
                    closed_at text,
                    is_open integer,
                    raw_order_json text
                );
                create table if not exists positions (
                    id integer primary key autoincrement,
                    symbol text unique not null,
                    quantity integer not null,
                    average_price real not null,
                    current_price real,
                    unrealized_pnl real,
                    strategy_name text,
                    trading_mode text,
                    opened_at text,
                    updated_at text
                );
                create table if not exists risk_events (
                    id integer primary key autoincrement,
                    bot_run_id integer,
                    timestamp text not null,
                    symbol text,
                    severity text not null,
                    event_type text not null,
                    message text not null,
                    blocked_trade integer,
                    rule_name text,
                    raw_data_json text
                );
                create table if not exists bot_logs (
                    id integer primary key autoincrement,
                    bot_run_id integer,
                    timestamp text not null,
                    level text not null,
                    module text,
                    message text not null,
                    raw_data_json text
                );
                create table if not exists bot_settings (
                    id integer primary key check (id = 1),
                    active_strategy text not null,
                    trading_mode text not null,
                    trading_enabled integer not null,
                    paper_trading_enabled integer not null,
                    live_trading_enabled integer not null,
                    kill_switch_enabled integer not null,
                    max_open_positions integer not null,
                    max_trades_per_day integer not null,
                    max_daily_losses integer not null,
                    risk_per_trade_percent real not null,
                    force_close_time text not null,
                    entry_window_start text not null,
                    entry_window_end text not null,
                    allowed_symbols text not null,
                    market_filter_symbols text not null,
                    created_at text not null,
                    updated_at text not null
                );
                """
            )
        self.ensure_default_settings()

    def ensure_default_settings(self) -> None:
        now = _now_iso()
        with self.connect() as connection:
            connection.execute(
                """
                insert or ignore into bot_settings (
                    id, active_strategy, trading_mode, trading_enabled,
                    paper_trading_enabled, live_trading_enabled, kill_switch_enabled,
                    max_open_positions, max_trades_per_day, max_daily_losses,
                    risk_per_trade_percent, force_close_time, entry_window_start,
                    entry_window_end, allowed_symbols, market_filter_symbols,
                    created_at, updated_at
                ) values (1, ?, ?, 1, 1, 0, 0, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    config.ORVWAP_STRATEGY_NAME,
                    "PAPER",
                    int(config.ORVWAP_MAX_POSITIONS),
                    int(config.ORVWAP_MAX_TRADES_PER_DAY),
                    int(config.ORVWAP_MAX_LOSING_TRADES_PER_DAY),
                    float(config.ORVWAP_RISK_PER_TRADE_PCT) * 100.0,
                    config.ORVWAP_FORCE_CLOSE_TIME,
                    config.ORVWAP_ENTRY_START,
                    config.ORVWAP_ENTRY_END,
                    _json(config.ORVWAP_TRADE_SYMBOLS),
                    _json([config.ORVWAP_MARKET_FILTER_SYMBOL, config.ORVWAP_TECH_FILTER_SYMBOL]),
                    now,
                    now,
                ),
            )

    def start_run(self, strategy_name: str, trading_mode: str, active_symbols: list[str]) -> int:
        with self.connect() as connection:
            cursor = connection.execute(
                """
                insert into bot_runs (
                    started_at, status, strategy_name, trading_mode, active_symbols, latest_heartbeat_at
                ) values (?, 'running', ?, ?, ?, ?)
                """,
                (_now_iso(), strategy_name, trading_mode, _json(active_symbols), _now_iso()),
            )
            return int(cursor.lastrowid)

    def finish_run(self, bot_run_id: int | None, status: str = "stopped", error_message: str | None = None) -> None:
        if bot_run_id is None:
            return
        with self.connect() as connection:
            connection.execute(
                "update bot_runs set stopped_at = ?, status = ?, error_message = ? where id = ?",
                (_now_iso(), status, error_message, bot_run_id),
            )

    def heartbeat(self, bot_run_id: int | None, status: str, current_loop_state: str) -> None:
        now = _now_iso()
        with self.connect() as connection:
            connection.execute(
                """
                insert into bot_heartbeats (
                    bot_run_id, timestamp, status, current_loop_state, active_strategy, trading_mode
                ) values (?, ?, ?, ?, ?, ?)
                """,
                (bot_run_id, now, status, current_loop_state, config.ACTIVE_STRATEGY, config.TRADING_MODE),
            )
            if bot_run_id is not None:
                connection.execute(
                    "update bot_runs set latest_heartbeat_at = ?, status = ? where id = ?",
                    (now, status, bot_run_id),
                )

    def log_signal(self, bot_run_id: int | None, signal_type: str, payload: dict) -> None:
        symbol = payload.get("symbol") or payload.get("ticker")
        passed = bool(payload.get("passed_all_entry_rules", payload.get("entry_approved", False)))
        market_allowed = payload.get("market_filter_allowed")
        if market_allowed is None:
            market_allowed = payload.get("spy_above_vwap") is not False
        with self.connect() as connection:
            connection.execute(
                """
                insert into signals (
                    bot_run_id, timestamp, symbol, strategy_name, signal_type, confidence, price,
                    opening_range_high, opening_range_low, opening_range_midpoint, vwap, atr,
                    volume_ratio, spread_percentage, market_filter_allowed, market_filter_reason,
                    passed_entry_rules, trade_executed, reason, skip_reason, raw_data_json
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    bot_run_id,
                    str(payload.get("timestamp") or _now_iso()),
                    symbol,
                    payload.get("strategy_name") or payload.get("strategy_version"),
                    signal_type.lower(),
                    payload.get("confidence"),
                    payload.get("price") or payload.get("entry_price"),
                    payload.get("opening_range_high"),
                    payload.get("opening_range_low"),
                    payload.get("opening_range_midpoint"),
                    payload.get("vwap"),
                    payload.get("atr") or payload.get("atr_14"),
                    payload.get("volume_ratio"),
                    payload.get("spread_percentage") or payload.get("spread"),
                    _bool(market_allowed),
                    payload.get("market_filter_reason"),
                    _bool(passed),
                    _bool(payload.get("trade_executed", False)),
                    payload.get("reason"),
                    payload.get("skip_reason") or payload.get("rejection_reason"),
                    _json(payload),
                ),
            )

    def log_trade(self, bot_run_id: int | None, payload: dict) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                insert into trades (
                    bot_run_id, timestamp, symbol, side, quantity, entry_price, exit_price,
                    stop_loss, take_profit, realized_pnl, unrealized_pnl, risk_reward,
                    order_status, broker_order_id, strategy_name, trading_mode, entry_reason,
                    exit_reason, opened_at, closed_at, is_open, raw_order_json
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    bot_run_id,
                    str(payload.get("timestamp") or _now_iso()),
                    payload["symbol"],
                    payload["side"],
                    payload.get("quantity"),
                    payload.get("entry_price"),
                    payload.get("exit_price"),
                    payload.get("stop_loss"),
                    payload.get("take_profit"),
                    payload.get("realized_pnl"),
                    payload.get("unrealized_pnl"),
                    payload.get("risk_reward"),
                    payload.get("order_status", "paper_filled"),
                    payload.get("broker_order_id"),
                    payload.get("strategy_name", config.ACTIVE_STRATEGY),
                    payload.get("trading_mode", config.TRADING_MODE),
                    payload.get("entry_reason"),
                    payload.get("exit_reason"),
                    payload.get("opened_at"),
                    payload.get("closed_at"),
                    _bool(payload.get("is_open", False)),
                    _json(payload.get("raw_order_json") or payload),
                ),
            )

    def upsert_position(self, payload: dict) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                insert into positions (
                    symbol, quantity, average_price, current_price, unrealized_pnl,
                    strategy_name, trading_mode, opened_at, updated_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(symbol) do update set
                    quantity = excluded.quantity,
                    average_price = excluded.average_price,
                    current_price = excluded.current_price,
                    unrealized_pnl = excluded.unrealized_pnl,
                    strategy_name = excluded.strategy_name,
                    trading_mode = excluded.trading_mode,
                    updated_at = excluded.updated_at
                """,
                (
                    payload["symbol"],
                    payload["quantity"],
                    payload["average_price"],
                    payload.get("current_price"),
                    payload.get("unrealized_pnl"),
                    payload.get("strategy_name", config.ACTIVE_STRATEGY),
                    payload.get("trading_mode", config.TRADING_MODE),
                    payload.get("opened_at") or _now_iso(),
                    _now_iso(),
                ),
            )

    def close_position(self, symbol: str) -> None:
        with self.connect() as connection:
            connection.execute("delete from positions where symbol = ?", (symbol,))

    def log_risk_event(
        self,
        bot_run_id: int | None,
        message: str,
        symbol: str | None = None,
        severity: str = "warning",
        event_type: str = "risk_block",
        blocked_trade: bool = True,
        rule_name: str | None = None,
        raw_data: dict | None = None,
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                insert into risk_events (
                    bot_run_id, timestamp, symbol, severity, event_type, message,
                    blocked_trade, rule_name, raw_data_json
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (bot_run_id, _now_iso(), symbol, severity, event_type, message, _bool(blocked_trade), rule_name, _json(raw_data)),
            )

    def log(self, bot_run_id: int | None, level: str, module: str, message: str, raw_data: dict | None = None) -> None:
        with self.connect() as connection:
            connection.execute(
                "insert into bot_logs (bot_run_id, timestamp, level, module, message, raw_data_json) values (?, ?, ?, ?, ?, ?)",
                (bot_run_id, _now_iso(), level, module, message, _json(raw_data)),
            )


_STORE = None


def get_observability_store() -> ObservabilityStore:
    global _STORE
    if _STORE is None:
        _STORE = ObservabilityStore()
    return _STORE
