-- ML Trade Brain v1 tables (run in Supabase SQL editor after database/schema.sql)

create table if not exists candidate_trades (
    id bigint generated always as identity primary key,
    created_at timestamptz not null default now(),
    event_timestamp timestamptz,
    strategy text not null,
    symbol text not null,
    side text not null default 'LONG',
    entry_price numeric,
    stop_price numeric,
    target_price numeric,
    strategy_approved boolean not null default false,
    payload jsonb not null default '{}'::jsonb
);

create table if not exists ml_features (
    id bigint generated always as identity primary key,
    created_at timestamptz not null default now(),
    candidate_trade_id bigint references candidate_trades(id),
    model_version text,
    feature_row jsonb not null default '{}'::jsonb
);

create table if not exists ml_predictions (
    id bigint generated always as identity primary key,
    created_at timestamptz not null default now(),
    event_timestamp timestamptz,
    strategy text,
    symbol text,
    ml_score numeric,
    ml_decision text,
    ml_threshold numeric,
    model_version text,
    top_reasons text,
    error text,
    payload jsonb not null default '{}'::jsonb
);

create table if not exists model_versions (
    id bigint generated always as identity primary key,
    created_at timestamptz not null default now(),
    model_version text unique not null,
    model_type text,
    threshold numeric,
    artifact_path text,
    metadata jsonb not null default '{}'::jsonb
);

create table if not exists model_runs (
    id bigint generated always as identity primary key,
    created_at timestamptz not null default now(),
    run_id text unique not null,
    model_version text,
    model_type text,
    status text not null,
    train_rows integer,
    test_rows integer,
    report jsonb not null default '{}'::jsonb
);
