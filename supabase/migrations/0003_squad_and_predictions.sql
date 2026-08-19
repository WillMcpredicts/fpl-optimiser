-- Squad state and model output.

-- My 15. Kept as a small history rather than a single mutable row, so a
-- transfer recommendation can be read back against the squad it was made for.
create table if not exists my_squad (
  id               bigserial primary key,
  season           text not null,
  gw               int  not null,
  source           text not null,          -- 'manual' | 'fpl_picks'
  bank             int  not null,          -- tenths of a million
  squad_value      int,
  free_transfers   int  not null default 1,
  chips_available  jsonb not null default '[]'::jsonb,
  chips_used       jsonb not null default '[]'::jsonb,
  is_current       boolean not null default true,
  created_at       timestamptz not null default now()
);
create unique index if not exists my_squad_current_idx
  on my_squad (season) where is_current;

create table if not exists my_squad_picks (
  squad_id         bigint not null references my_squad(id) on delete cascade,
  player_id        int    not null,
  player_code      int,
  position         int    not null,        -- 1..15, FPL pick order
  is_captain       boolean not null default false,
  is_vice_captain  boolean not null default false,
  -- What I paid, which sets sale value: FPL returns half of any rise, rounded
  -- down to 0.1m (transfers_sell_on_fee = 0.5 in the live game settings).
  purchase_price   int,
  selling_price    int,
  primary key (squad_id, player_id)
);

-- Model output. principle 8: the breakdown is the point, not the total.
-- final_score must always equal base_score + fixture_adjustment + trend_adjustment
-- so the UI can show its working and any drift is a visible bug.
create table if not exists predicted_points (
  season               text not null,
  player_id            int  not null,
  gw                   int  not null,
  fixture_id           int,
  opponent_id          int,
  was_home             boolean,
  -- component parts
  minutes_probability  numeric not null,   -- 0..1, the dominant driver
  expected_minutes     numeric not null,
  base_score           numeric not null,
  fixture_adjustment   numeric not null default 0,
  trend_adjustment     numeric not null default 0,
  bps_adjustment       numeric not null default 0,
  final_score          numeric not null,
  -- per-component detail: attacking/defensive/appearance splits, the opponent
  -- strength differential used, which trend flags applied, and why.
  confidence_breakdown jsonb not null default '{}'::jsonb,
  model_version        text not null,
  computed_at          timestamptz not null default now(),
  primary key (season, player_id, gw)
);
create index if not exists pp_gw_idx on predicted_points (season, gw, final_score desc);

-- Ranked transfer suggestions, written by the planner so the UI is a pure read
-- and a suggestion can be compared against what actually happened.
create table if not exists transfer_suggestions (
  id                  bigserial primary key,
  season              text not null,
  gw                  int  not null,
  squad_id            bigint references my_squad(id) on delete cascade,
  player_out          int  not null,
  player_in           int  not null,
  out_cost            int,
  in_cost             int,
  cash_delta          int,                 -- negative means it costs me money
  transfers_used      int  not null default 1,
  hit_cost            int  not null default 0,   -- 0 or -4 per extra transfer
  gross_gain_3gw      numeric not null,
  net_gain_3gw        numeric not null,    -- gross minus hit_cost
  reasoning           jsonb not null default '{}'::jsonb,
  rank                int,
  created_at          timestamptz not null default now()
);
create index if not exists ts_gw_idx on transfer_suggestions (season, gw, rank);
