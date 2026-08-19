-- Raw layer: a faithful copy of what the sources say, per season.
--
-- Everything is keyed by (season, id) because FPL reassigns element and team
-- ids every summer. `code` is the stable cross-season identity and is what
-- historical joins must use -- joining last season's shots to this season's
-- players by `id` silently attaches data to the wrong footballer.

create table if not exists teams (
  season                  text    not null,
  id                      int     not null,
  code                    int     not null,
  name                    text    not null,
  short_name              text    not null,
  strength                int,
  strength_overall_home   int,
  strength_overall_away   int,
  strength_attack_home    int,
  strength_attack_away    int,
  strength_defence_home   int,
  strength_defence_away   int,
  elo                     numeric,
  -- which link in the fallback chain supplied `elo`; see ingest/elo.py
  elo_source              text,
  updated_at              timestamptz not null default now(),
  primary key (season, id)
);
create index if not exists teams_code_idx on teams (code);

create table if not exists players (
  season                       text not null,
  id                           int  not null,
  code                         int  not null,
  first_name                   text,
  second_name                  text,
  web_name                     text not null,
  team_id                      int  not null,
  element_type                 int  not null,  -- 1 GK, 2 DEF, 3 MID, 4 FWD
  now_cost                     int,            -- tenths of a million
  status                       text,           -- a, d, i, s, u, n
  news                         text,
  chance_of_playing_next_round int,
  selected_by_percent          numeric,
  -- season-to-date totals as FPL reports them
  minutes                      int,
  starts                       int,
  total_points                 int,
  bonus                        int,
  bps                          int,
  goals_scored                 int,
  assists                      int,
  clean_sheets                 int,
  goals_conceded               int,
  saves                        int,
  expected_goals               numeric,
  expected_assists             numeric,
  expected_goals_conceded      numeric,
  defensive_contribution       int,
  updated_at                   timestamptz not null default now(),
  primary key (season, id)
);
create index if not exists players_code_idx on players (code);
create index if not exists players_team_idx on players (season, team_id);

create table if not exists fixtures (
  season             text not null,
  id                 int  not null,
  event              int,             -- gameweek; null for unscheduled
  kickoff_time       timestamptz,
  team_h             int  not null,
  team_a             int  not null,
  team_h_difficulty  int,
  team_a_difficulty  int,
  team_h_score       int,
  team_a_score       int,
  finished           boolean not null default false,
  updated_at         timestamptz not null default now(),
  primary key (season, id)
);
create index if not exists fixtures_event_idx on fixtures (season, event);

-- Per-player, per-gameweek actuals. Backfilled from the vaastav archive for
-- past seasons and from the FPL API for the live one. This is the table the
-- minutes model and the rolling xG rates read from.
create table if not exists player_gameweeks (
  season                  text not null,
  player_id               int  not null,
  player_code             int  not null,
  gw                      int  not null,
  fixture_id              int  not null,
  opponent_team           int,
  was_home                boolean,
  kickoff_time            timestamptz,
  minutes                 int  not null default 0,
  starts                  int  not null default 0,
  total_points            int  not null default 0,
  bonus                   int  not null default 0,
  bps                     int  not null default 0,
  goals_scored            int  not null default 0,
  assists                 int  not null default 0,
  clean_sheets            int  not null default 0,
  goals_conceded          int  not null default 0,
  saves                   int  not null default 0,
  expected_goals          numeric,
  expected_assists        numeric,
  expected_goals_conceded numeric,
  defensive_contribution  int,
  yellow_cards            int  not null default 0,
  red_cards               int  not null default 0,
  value                   int,
  primary key (season, player_id, gw, fixture_id)
);
create index if not exists pgw_code_idx on player_gameweeks (player_code, season, gw);
create index if not exists pgw_gw_idx on player_gameweeks (season, gw);

-- Shot-level events, sourced from FPL-Core-Insights shots.csv joined through
-- matches.csv (for team/opponent, which the shot rows do not carry) and
-- players.csv (for shooter position). Premier League only: the source mixes in
-- Champions League, Europa, Conference and EFL Cup, where FPL team ids are blank.
create table if not exists match_events (
  season          text not null,
  match_id        text not null,
  shot_index      int  not null,
  fpl_fixture_id  int,
  gw              int,
  kickoff_time    timestamptz,
  team_id         int  not null,
  opponent_id     int  not null,
  is_home         boolean not null,
  player_id       int,
  player_code     int,
  player_position text,            -- shooter's position, via players.csv
  minute          int,
  body_part       text,            -- left-foot | right-foot | head
  situation       text,            -- assisted | regular | fast-break | corner | free-kick | set-piece | throw-in-set-piece
  zone            text,            -- derived from start_x/start_y
  start_x         numeric,
  start_y         numeric,
  xg              numeric,
  xgot            numeric,
  outcome         text,            -- goal | save | miss | block | post
  is_goal         boolean not null default false,
  primary key (season, match_id, shot_index)
);
create index if not exists me_team_idx on match_events (season, team_id, gw);
create index if not exists me_opp_idx  on match_events (season, opponent_id, gw);

-- Team-match aggregates from matches.csv. Carries the DENOMINATORS that
-- principle 1 needs: you cannot compute "headers conceded per aerial situation
-- faced" without knowing how many aerial duels there were.
create table if not exists team_match_stats (
  season                 text not null,
  match_id               text not null,
  team_id                int  not null,
  opponent_id            int  not null,
  gw                     int,
  kickoff_time           timestamptz,
  is_home                boolean not null,
  elo                    numeric,
  opponent_elo           numeric,
  goals_for              int,
  goals_against          int,
  xg                     numeric,
  xg_conceded            numeric,
  xg_open_play           numeric,
  xg_set_play            numeric,
  non_penalty_xg         numeric,
  shots                  int,
  shots_on_target        int,
  shots_inside_box       int,
  shots_outside_box      int,
  big_chances            int,
  corners                int,
  crosses_accurate       int,
  aerial_duels_won       int,
  aerial_duels_won_pct   numeric,
  ground_duels_won       int,
  tackles_won            int,
  interceptions          int,
  clearances             int,
  blocks                 int,
  keeper_saves           int,
  touches_in_opp_box     int,
  primary key (season, match_id, team_id)
);
create index if not exists tms_team_idx on team_match_stats (season, team_id, gw);

-- One row per ingestion run, so the UI can honestly say how fresh it is and a
-- failed scrape is visible rather than silently serving stale numbers.
create table if not exists ingest_runs (
  id          bigserial primary key,
  source      text not null,
  season      text,
  started_at  timestamptz not null default now(),
  finished_at timestamptz,
  status      text not null default 'running',  -- running | ok | failed
  rows_written int,
  detail      text
);
