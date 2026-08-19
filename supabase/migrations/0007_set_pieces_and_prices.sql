-- Set-piece duties and price movement.
--
-- Penalty order is the single most valuable field here. A designated taker gets
-- the highest-expected-value shot in football, repeatedly, and nothing else in
-- the model distinguishes them from a team-mate who never takes one.
--
-- Price fields matter over a season rather than a week: team value compounds,
-- and buying before a rise is free budget.

alter table players
  add column if not exists penalties_order        int,
  add column if not exists penalties_text         text,
  add column if not exists direct_fk_order        int,
  add column if not exists corners_fk_order       int,
  add column if not exists cost_change_event      int,
  add column if not exists cost_change_start      int,
  add column if not exists transfers_in_event     int,
  add column if not exists transfers_out_event    int,
  add column if not exists form                   numeric,
  add column if not exists points_per_game        numeric,
  add column if not exists ict_index              numeric,
  add column if not exists expected_goals_per_90  numeric,
  add column if not exists expected_assists_per_90 numeric,
  add column if not exists defensive_contribution_per_90 numeric;

-- Chip planning. One row per chip per gameweek considered, so the UI can show
-- why a week was chosen rather than just naming it.
create table if not exists chip_plans (
  id             bigserial primary key,
  season         text not null,
  chip           text not null,          -- 'bboost' | '3xc'
  gw             int  not null,
  value_points   numeric not null,       -- extra points from playing it that week
  detail         jsonb not null default '{}'::jsonb,
  is_best        boolean not null default false,
  created_at     timestamptz not null default now(),
  unique (season, chip, gw)
);
