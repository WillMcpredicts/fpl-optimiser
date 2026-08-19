-- Derived layer + trend flags.
--
-- Two deliberate additions to the shape given in the brief:
--
--   `as_of_gw`  -- every derived row records the gameweek it was computed as
--               of, using only matches played before it. Without this the
--               backtest in principle 6 cannot prove it avoided lookahead;
--               with it, replaying a past season is just a filter.
--
--   the window column is named `window_label`, because `window` is a reserved
--   word in Postgres and would need quoting at every call site.

create table if not exists team_rate_stats (
  season        text not null,
  as_of_gw      int  not null,
  team_id       int  not null,
  window_label  text not null,     -- e.g. 'last4', 'prev4', 'season'
  stat_type     text not null,     -- e.g. 'headers_conceded_per_aerial_faced'
  -- principle 1: opportunity-normalised, never a raw count
  events        numeric not null,  -- numerator
  opportunities numeric not null,  -- denominator
  rate          numeric not null,
  sample_size   int     not null,  -- opportunities, as an integer event count
  -- principle 2: league-relative
  league_mean   numeric not null,
  league_stdev  numeric not null,
  z_score       numeric,
  -- principle 3: empirical Bayes shrinkage toward the league mean
  shrunk_rate   numeric not null,
  shrunk_z      numeric,
  -- principle 4: below the floor this row is stored but never promoted
  meets_sample_floor boolean not null,
  computed_at   timestamptz not null default now(),
  primary key (season, as_of_gw, team_id, window_label, stat_type)
);
create index if not exists trs_lookup_idx on team_rate_stats (season, as_of_gw, stat_type);

-- Only rows that cleared the minimum sample floor AND the persistence check
-- land here. The predictor and the UI read trends from this table and never
-- from team_rate_stats, so an unvetted rate cannot leak into a score.
create table if not exists trend_flags (
  id                      bigserial primary key,
  season                  text not null,
  as_of_gw                int  not null,
  team_id                 int  not null,
  stat_type               text not null,
  direction               text not null,   -- 'vulnerable' | 'strong'
  confidence              text not null,   -- 'watch' | 'medium' | 'high'
  sample_size             int  not null,
  z_score                 numeric not null,
  shrunk_rate             numeric not null,
  league_mean             numeric not null,
  -- principle 5: high confidence requires both non-overlapping windows
  first_window_confirmed  boolean not null default false,
  second_window_confirmed boolean not null default false,
  -- principle 7: the capped multiplier this trend is allowed to contribute
  points_multiplier       numeric not null default 1.0,
  label                   text,            -- human-readable, for the UI
  created_at              timestamptz not null default now(),
  unique (season, as_of_gw, team_id, stat_type)
);
create index if not exists tf_team_idx on trend_flags (season, as_of_gw, team_id);

alter table trend_flags
  drop constraint if exists trend_flags_confidence_check,
  add constraint trend_flags_confidence_check
  check (confidence in ('watch', 'medium', 'high'));

-- A 'high' flag is a contradiction unless both windows confirmed it.
alter table trend_flags
  drop constraint if exists trend_flags_persistence_check,
  add constraint trend_flags_persistence_check
  check (confidence <> 'high' or (first_window_confirmed and second_window_confirmed));

-- Results of the principle 6 backtest. Trends are not allowed to influence
-- live predicted points until a passing row exists here and has been accepted.
create table if not exists backtest_results (
  id                    bigserial primary key,
  season                text not null,
  stat_type             text not null,
  confidence            text not null,
  flags_evaluated       int  not null,
  -- forward performance of flagged teams vs the league baseline
  baseline_mae          numeric,
  trend_mae             numeric,
  improvement_pct       numeric,
  hit_rate              numeric,
  baseline_hit_rate     numeric,
  passed                boolean not null default false,
  notes                 text,
  created_at            timestamptz not null default now()
);

-- The gate itself. Nothing reads trend_flags into a live score until a row
-- here says the user accepted the thresholds.
create table if not exists trend_engine_gate (
  id             int primary key default 1,
  enabled        boolean not null default false,
  min_confidence text    not null default 'medium',
  max_adjustment numeric not null default 0.15,   -- principle 7 cap
  accepted_at    timestamptz,
  accepted_note  text,
  constraint trend_engine_gate_singleton check (id = 1)
);
insert into trend_engine_gate (id, enabled) values (1, false) on conflict do nothing;
