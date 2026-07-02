create extension if not exists pgcrypto;

create table if not exists bot_runs (
    id uuid primary key default gen_random_uuid(),
    started_at timestamptz not null default now(),
    stopped_at timestamptz,
    status text not null,
    strategy_name text not null,
    trading_mode text not null,
    active_symbols jsonb,
    error_message text,
    latest_heartbeat_at timestamptz
);

create table if not exists bot_heartbeats (
    id uuid primary key default gen_random_uuid(),
    bot_run_id uuid references bot_runs(id) on delete set null,
    timestamp timestamptz not null default now(),
    status text not null,
    current_loop_state text,
    active_strategy text,
    trading_mode text
);

create table if not exists signals (
    id uuid primary key default gen_random_uuid(),
    bot_run_id uuid references bot_runs(id) on delete set null,
    timestamp timestamptz not null default now(),
    symbol text,
    strategy_name text,
    signal_type text,
    confidence numeric,
    price numeric,
    opening_range_high numeric,
    opening_range_low numeric,
    opening_range_midpoint numeric,
    vwap numeric,
    atr numeric,
    volume_ratio numeric,
    spread_percentage numeric,
    market_filter_allowed boolean,
    market_filter_reason text,
    passed_entry_rules boolean,
    trade_executed boolean default false,
    reason text,
    skip_reason text,
    raw_data_json jsonb
);

create table if not exists trades (
    id uuid primary key default gen_random_uuid(),
    bot_run_id uuid references bot_runs(id) on delete set null,
    timestamp timestamptz not null default now(),
    symbol text not null,
    side text not null,
    quantity integer,
    entry_price numeric,
    exit_price numeric,
    stop_loss numeric,
    take_profit numeric,
    realized_pnl numeric,
    unrealized_pnl numeric,
    risk_reward numeric,
    order_status text,
    broker_order_id text,
    strategy_name text,
    trading_mode text,
    entry_reason text,
    exit_reason text,
    opened_at timestamptz,
    closed_at timestamptz,
    is_open boolean default false,
    raw_order_json jsonb
);

create table if not exists positions (
    id uuid primary key default gen_random_uuid(),
    symbol text unique not null,
    quantity integer not null,
    average_price numeric not null,
    current_price numeric,
    unrealized_pnl numeric,
    strategy_name text,
    trading_mode text,
    opened_at timestamptz,
    updated_at timestamptz not null default now()
);

create table if not exists risk_events (
    id uuid primary key default gen_random_uuid(),
    bot_run_id uuid references bot_runs(id) on delete set null,
    timestamp timestamptz not null default now(),
    symbol text,
    severity text not null,
    event_type text not null,
    message text not null,
    blocked_trade boolean default false,
    rule_name text,
    raw_data_json jsonb
);

create table if not exists bot_logs (
    id uuid primary key default gen_random_uuid(),
    bot_run_id uuid references bot_runs(id) on delete set null,
    timestamp timestamptz not null default now(),
    level text not null,
    module text,
    message text not null,
    raw_data_json jsonb
);

create table if not exists bot_settings (
    id uuid primary key default gen_random_uuid(),
    active_strategy text not null default 'opening_range_vwap_momentum_v1',
    trading_mode text not null default 'PAPER',
    trading_enabled boolean not null default true,
    paper_trading_enabled boolean not null default true,
    live_trading_enabled boolean not null default false,
    kill_switch_enabled boolean not null default false,
    max_open_positions integer not null default 1,
    max_trades_per_day integer not null default 3,
    max_daily_losses integer not null default 2,
    risk_per_trade_percent numeric not null default 0.375,
    force_close_time text not null default '15:55',
    entry_window_start text not null default '09:35',
    entry_window_end text not null default '10:30',
    allowed_symbols jsonb not null default '["NVDA","TSLA","AMD","AAPL","META","MSFT","AMZN"]'::jsonb,
    market_filter_symbols jsonb not null default '["SPY","QQQ"]'::jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

insert into bot_settings (
    active_strategy, trading_mode, trading_enabled, paper_trading_enabled,
    live_trading_enabled, kill_switch_enabled, max_open_positions,
    max_trades_per_day, max_daily_losses, risk_per_trade_percent,
    force_close_time, entry_window_start, entry_window_end,
    allowed_symbols, market_filter_symbols
) values (
    'opening_range_vwap_momentum_v1', 'PAPER', true, true, false, false, 1,
    3, 2, 0.375, '15:55', '09:35', '10:30',
    '["NVDA","TSLA","AMD","AAPL","META","MSFT","AMZN"]'::jsonb,
    '["SPY","QQQ"]'::jsonb
) on conflict do nothing;

create index if not exists idx_signals_timestamp on signals(timestamp desc);
create index if not exists idx_trades_timestamp on trades(timestamp desc);
create index if not exists idx_risk_events_timestamp on risk_events(timestamp desc);
create index if not exists idx_bot_logs_timestamp on bot_logs(timestamp desc);
