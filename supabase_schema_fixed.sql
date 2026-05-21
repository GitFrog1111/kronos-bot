-- Kronos real-time tables (fixed for Supabase SQL Editor)

-- Singleton signal row (always id=1)
create table if not exists public.kronos_signals (
    id int primary key default 1 check (id = 1),
    timestamp timestamptz not null default now(),
    signal text check (signal in ('up','down','none')) default 'none',
    confidence double precision default 0,
    btc_price double precision default 0,
    predicted_price double precision default 0
);
create unique index if not exists idx_kronos_signals_singleton on public.kronos_signals (id);

-- Trade journal
create table if not exists public.kronos_trades (
    id bigserial primary key,
    timestamp timestamptz not null default now(),
    market text,
    direction text check (direction in ('up','down')),
    amount double precision default 0,
    odds double precision default 0,
    result text check (result in ('win','loss','pending')) default 'pending',
    pnl double precision default 0
);
create index if not exists idx_kronos_trades_timestamp on public.kronos_trades(timestamp desc);

-- Singleton status row (always id=1)
create table if not exists public.kronos_status (
    id int primary key default 1 check (id = 1),
    updated_at timestamptz not null default now(),
    online boolean default true,
    market text default '',
    market_close timestamptz,
    prediction text check (prediction in ('up','down','none')) default 'none',
    confidence double precision default 0,
    odds_up double precision default 0,
    odds_down double precision default 0,
    recommended_bet double precision,
    recommended_direction text check (recommended_direction in ('up','down')),
    balance double precision default 100
);
create unique index if not exists idx_kronos_status_singleton on public.kronos_status (id);

-- RLS policies (allow all for now)
alter table if exists public.kronos_signals enable row level security;
alter table if exists public.kronos_trades enable row level security;
alter table if exists public.kronos_status enable row level security;
create policy if not exists "Allow all" on public.kronos_signals for all to anon, authenticated using (true) with check (true);
create policy if not exists "Allow all" on public.kronos_trades for all to anon, authenticated using (true) with check (true);
create policy if not exists "Allow all" on public.kronos_status for all to anon, authenticated using (true) with check (true);

-- Enable realtime (just add; safe to re-run)
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_publication WHERE pubname = 'supabase_realtime') THEN
        ALTER PUBLICATION supabase_realtime ADD TABLE public.kronos_signals;
        ALTER PUBLICATION supabase_realtime ADD TABLE public.kronos_trades;
        ALTER PUBLICATION supabase_realtime ADD TABLE public.kronos_status;
    END IF;
END $$;
