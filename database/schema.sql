create table if not exists experiments (
    id bigint generated always as identity primary key,
    run_id text unique not null,
    created_at timestamptz not null default now(),
    strategy text not null,
    stage text not null,
    status text not null,
    passes_gate boolean not null,
    start_date date,
    end_date date,
    symbols text[] default '{}',
    report jsonb not null default '{}'::jsonb,
    validation_gate jsonb not null default '{}'::jsonb,
    parameters jsonb not null default '{}'::jsonb
);

create table if not exists signals (
    id bigint generated always as identity primary key,
    created_at timestamptz not null default now(),
    event_timestamp timestamptz,
    strategy text not null,
    symbol text not null,
    mode text not null,
    event_type text not null,
    entry_approved boolean not null default false,
    rejection_reason text,
    price numeric,
    stop_price numeric,
    target_price numeric,
    payload jsonb not null default '{}'::jsonb
);

create table if not exists orders (
    id bigint generated always as identity primary key,
    created_at timestamptz not null default now(),
    broker text not null,
    broker_order_id text,
    strategy text not null,
    symbol text not null,
    side text not null,
    quantity integer not null,
    order_type text not null default 'market',
    time_in_force text not null default 'day',
    status text not null,
    requested_price numeric,
    filled_price numeric,
    payload jsonb not null default '{}'::jsonb
);

create table if not exists fills (
    id bigint generated always as identity primary key,
    created_at timestamptz not null default now(),
    broker text not null,
    broker_order_id text,
    symbol text not null,
    side text not null,
    quantity integer not null,
    filled_price numeric not null,
    filled_at timestamptz,
    payload jsonb not null default '{}'::jsonb
);

create table if not exists positions (
    id bigint generated always as identity primary key,
    updated_at timestamptz not null default now(),
    broker text not null,
    symbol text not null,
    quantity integer not null,
    average_entry_price numeric not null,
    market_value numeric,
    payload jsonb not null default '{}'::jsonb,
    unique (broker, symbol)
);

create table if not exists risk_events (
    id bigint generated always as identity primary key,
    created_at timestamptz not null default now(),
    strategy text,
    severity text not null,
    event_type text not null,
    message text not null,
    payload jsonb not null default '{}'::jsonb
);

create table if not exists daily_reports (
    id bigint generated always as identity primary key,
    report_date date not null unique,
    created_at timestamptz not null default now(),
    status text not null,
    summary text not null,
    payload jsonb not null default '{}'::jsonb
);

create table if not exists research_reports (
    id bigint generated always as identity primary key,
    created_at timestamptz not null default now(),
    strategy_name text not null,
    start_date date,
    end_date date,
    profile text,
    status text not null,
    total_return numeric,
    profit_factor numeric,
    expectancy numeric,
    win_rate numeric,
    max_drawdown numeric,
    monte_carlo_probability_of_loss numeric,
    recommendation text,
    report_json jsonb not null default '{}'::jsonb
);
