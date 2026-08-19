-- Output of the squad optimiser.
--
-- `xi_points` is the objective: STARTING eleven points across the horizon, with
-- the captain counted twice. Deliberately not the whole 15 -- bench points do
-- not score, and optimising all 15 buys a strong bench and a weaker XI.
--
-- `detail` holds the squad and the per-gameweek starters and captain. The XI
-- changes week to week (you can reshuffle without a transfer), so the roles are
-- stored per gameweek rather than once.

create table if not exists optimal_squads (
  id                 bigserial primary key,
  season             text not null,
  gw                 int  not null,
  mode               text not null,          -- 'dream' | 'reachable'
  transfers_allowed  int,                    -- null for an unconstrained build
  budget             int  not null,
  xi_points          numeric not null,
  squad_cost         int  not null,
  hit_cost           int  not null default 0,
  net_points         numeric not null,       -- xi_points minus hit_cost
  detail             jsonb not null default '{}'::jsonb,
  created_at         timestamptz not null default now()
);
create index if not exists optimal_squads_lookup_idx
  on optimal_squads (season, gw, mode, transfers_allowed);
