-- Multi-gameweek transfer plan.
--
-- One row per gameweek in the horizon: what to do that week, what the XI is
-- worth, and what holding the current squad would have scored instead. Keyed to
-- the squad it was built from, so a plan for a team you no longer have is
-- hidden rather than shown.

create table if not exists multiweek_plan (
  id            bigserial primary key,
  season        text not null,
  squad_id      bigint references my_squad(id) on delete cascade,
  gw            int  not null,
  step          int  not null,
  xi_points     numeric not null,
  hold_points   numeric not null,     -- same gameweek, no transfers ever made
  hits          int  not null default 0,
  free_before   int,
  transfers     jsonb not null default '[]'::jsonb,
  captain       int,
  created_at    timestamptz not null default now(),
  unique (season, squad_id, gw)
);
create index if not exists multiweek_plan_squad_idx on multiweek_plan (squad_id, step);
