-- Autovista AI Orchestrator — shared orchestration store (Supabase).
-- Apply with `supabase db push`. This dir is self-contained: nothing in orchestrator/
-- imports it, so it can be dropped on handover to a CRM that already has its own store.

create extension if not exists "pgcrypto";

-- Dealership tenants. Regions/branches live on leads/assignments for scope filtering.
create table if not exists accounts (
    id         text primary key,
    name       text not null,
    brand      text not null default 'Autovista',
    created_at timestamptz not null default now()
);

-- Active monthly focus. focus_type = service|product; goal change regenerates the script.
create table if not exists goals (
    id             text primary key,
    account_id     text not null references accounts(id),
    month          text not null,                 -- 'YYYY-MM'
    focus_type     text not null check (focus_type in ('service','product')),
    focus_detail   text not null,
    script_version text not null default 'v1',
    set_by         text not null default 'human',
    active         boolean not null default true,
    created_at     timestamptz not null default now()
);
create index if not exists goals_account_active_idx on goals(account_id, active);

-- How many to reach out / close / follow up — drives dashboard progress bars.
create table if not exists targets (
    id         text primary key,
    account_id text not null references accounts(id),
    period     text not null,                     -- 'YYYY-MM'
    reach_out  integer not null default 0,
    close      integer not null default 0,
    follow_up  integer not null default 0,
    created_at timestamptz not null default now()
);

-- Demo CRM leads (StoreCRMAdapter reads these). Real CRMs supply their own source.
create table if not exists leads (
    id               text primary key,
    account_id       text not null references accounts(id),
    name             text not null,
    phone            text not null,
    vehicle_model    text default '',
    service_due_date text default '',
    source           text default 'Direct',
    region           text default '',
    branch           text default '',
    status           text default 'pending',
    lead_score       integer,
    created_at       timestamptz not null default now()
);
create index if not exists leads_account_scope_idx on leads(account_id, region, branch);

-- A lead queued/dispatched under a goal, on a DID.
create table if not exists assignments (
    id            text primary key,
    account_id    text not null references accounts(id),
    lead_id       text not null references leads(id),
    region        text default '',
    branch        text default '',
    goal_context  jsonb not null,
    did           text default '',
    execution_id  text default '',
    state         text not null default 'pending',
    created_at    timestamptz not null default now()
);
create index if not exists assignments_scope_idx on assignments(account_id, region, branch);
create index if not exists assignments_exec_idx on assignments(execution_id);

-- The Commitment Ledger — heart of Pain A. Never dropped by a goal change.
create table if not exists commitments (
    id                text primary key,
    account_id        text not null references accounts(id),
    lead_id           text not null references leads(id),
    region            text default '',
    branch            text default '',
    due_at            timestamptz not null,
    goal_context      jsonb not null,
    note              text default '',
    sla_hours         double precision not null default 24,
    retries           integer not null default 0,
    max_retries       integer not null default 4,
    state             text not null default 'pending',
    last_execution_id text default '',
    created_at        timestamptz not null default now(),
    updated_at        timestamptz not null default now()
);
create index if not exists commitments_due_idx on commitments(state, due_at);
create index if not exists commitments_scope_idx on commitments(account_id, region, branch);

-- Result of a dispatched call, correlated by execution_id (== Chat360 dlr_id).
create table if not exists call_outcomes (
    id             text primary key,
    account_id     text not null references accounts(id),
    execution_id   text not null,
    lead_id        text not null references leads(id),
    goal_context   jsonb not null,
    call_status    text not null default 'completed',
    outcome        text default '',
    duration_sec   integer not null default 0,
    callback_at    text default '',
    transcript_ref text default '',
    recording_url  text default '',
    extracted      jsonb not null default '{}',
    region         text default '',
    branch         text default '',
    created_at     timestamptz not null default now()
);
create index if not exists call_outcomes_exec_idx on call_outcomes(execution_id);
create index if not exists call_outcomes_scope_idx on call_outcomes(account_id, region, branch);

-- Pre-aggregated metrics per scope+period (the dashboard reads these for fast analytics).
create table if not exists rollups (
    id          text primary key,
    account_id  text not null references accounts(id),
    scope_level text not null check (scope_level in ('all','region','branch')),
    scope_value text not null default '',
    period      text not null,
    payload     jsonb not null,
    narrative   text default '',
    created_at  timestamptz not null default now()
);
create index if not exists rollups_lookup_idx on rollups(account_id, scope_level, scope_value, period);
