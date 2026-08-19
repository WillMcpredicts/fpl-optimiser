# FPL Optimiser

Personal-use tool for scoring an FPL squad and planning transfers. Next.js on
Vercel, Supabase Postgres, Python ingestion on GitHub Actions.

Separate from the Prem Predictor prediction-league app, which lives in its own
repo and its own Supabase project.

## Status

| Phase | Scope | State |
|---|---|---|
| 1 | FPL + historical ingestion, predicted points table | **Done** |
| 2 | Trend engine, backtest, sign-off gate | Not started |
| 3 | Squad import, transfer planner, full UI | Not started |
| 4 | Automated ingestion schedule | Not started |

## What was confirmed before building

The three things section 12 of the brief said not to assume.

**Transfer rules.** From the live API's own `game_settings`:
`max_extra_free_transfers = 4`, so 1 per week plus 4 banked = **5 maximum**, and
**-4 points** per transfer beyond the free ones. Chips are two full sets, one per
half of the season. The brief's assumptions hold.

**FPL-Core-Insights granularity.** `shots.csv` has real shot-level data and, for
Premier League matches, every field checked was fully populated (228/228 rows):
`body_part` (left-foot/right-foot/head), `situation` (assisted, regular,
fast-break, corner, free-kick, set-piece, throw-in-set-piece), `start_x`/`start_y`
for zone of origin, `xg`, `xgot`, `goal_mouth_location` and `outcome`. **The
Understat fallback is not needed.** Three joins worth knowing:

- Shots carry no team id, only `is_home` + `match_id`. Team and opponent resolve
  through `matches.csv`, which also carries the aerial/duel **denominators** that
  opportunity-normalised rates need.
- Shooter position is not on the shot row; it joins through `players.csv`.
- Filter `tournament == 'prem'`. The files mix in Champions League, Europa,
  Conference and EFL Cup, where FPL team ids are blank.

**Squad import needs authentication.** `my-team/{id}/` returns **403** without a
session cookie, and `entry/{id}/event/{gw}/picks/` returns 404 until a deadline
has passed. Manual entry is therefore mandatory for GW1; from GW2 the previous
gameweek's locked squad can be pulled automatically.

## Things that bite

**Season-scoped ids.** FPL reassigns element and team ids every summer. `code`
is the stable identity. Anything crossing a season boundary joins on `code`, or
it silently attaches last season's data to a different footballer.

**BPS was rewritten for 2026/27.** Being tackled is no longer penalised, CBI
scores per three actions rather than two, and keeper saves were restructured. The
model therefore carries **no BPS over/under-performance term** — calibrating one
on 2025/26 data would fit a formula that no longer exists. Base bonus rates are
still used and are flagged in each player's breakdown.

**The season has not started.** No gameweeks are played, so every rate comes from
2025/26 priors. The trend engine's minimum sample floor and persistence check
mean no trend can legitimately be flagged until roughly GW9.

**Elo is unresolved pre-season.** FPL-Core-Insights ships the 2026/27 `teams.csv`
with `elo` blank, the direct ClubElo API was unreachable when tested, and the FPL
API collapses to a coarse 1-5 strength scale until the season starts. `ingest/elo.py`
resolves it in order — this season's Elo, then last season's carried forward by
`code`, then a promoted-side prior — and records which source each team used, so
a projection resting on a guess does not look as solid as one resting on 38 games.

## Setup

```bash
npm install
python3 -m venv .venv && ./.venv/bin/pip install -r ingest/requirements.txt
cp .env.example .env.local   # fill in Supabase, APP_PASSWORD, AUTH_SECRET
```

Apply `supabase/migrations/*.sql` in numerical order in the Supabase SQL editor.

## Running

```bash
npm run dev
```

```bash
./.venv/bin/python ingest/run.py all
```

`run.py` takes `all`, `history`, `fpl` or `predict`. `history` backfills the
vaastav archive and only needs running once per past season.

To see the table without a database, generate a local snapshot — the app falls
back to it and says on screen that it is doing so:

```bash
./.venv/bin/python ingest/dryrun.py 3 --snapshot
```

## Layout

```
app/            Next.js routes. Predicted points is live; the rest are Phase 2/3 stubs.
lib/            Supabase reader, dataset assembly, password gate.
ingest/
  config.py     Season constants and source URLs
  common.py     HTTP, chunked PostgREST upserts, ingest_runs logging
  fpl.py        Live FPL API -> teams, players, fixtures, gameweek actuals
  history.py    vaastav archive backfill
  elo.py        Team strength with a recorded fallback chain
  depth.py      Depth-chart minutes priors
  rates.py      Per-player rates with empirical-Bayes shrinkage
  scoring.py    2026/27 scoring constants and the Poisson maths
  model.py      build_predictions(): the single scoring path
  dryrun.py     Same path, no database, plus snapshot output
supabase/migrations/
```

## How a score is built

`final_score = base_score + fixture_adjustment + trend_adjustment`

`base_score` scores the player against a league-average opponent at a neutral
venue. `fixture_adjustment` is the delta from their actual opponent, venue and
Elo gap. `trend_adjustment` is **zero until the trend engine passes its backtest
and the thresholds are signed off**. Every figure in the UI expands to show its
components, underlying rates, evidence in 90s played and fixture detail.

Two shrinkage layers keep small samples honest:

- **Rates** are blended toward a positional league mean, weighted by 90s played,
  and scaled by team strength for players with no history — otherwise every
  promoted-club signing inherits a league-average xG90.
- **Minutes** are shrunk toward a **depth-chart prior** built from price rank
  within club and position. Historical minutes cannot see a transfer, a promotion
  to first choice, or a return from injury, and pre-season those are exactly the
  players a projection gets most wrong. The chart identifies the first-choice
  keeper at 18 of 20 clubs.

## Verification done

- Migrations applied against real Postgres via pglite: 15 tables, 30 indexes.
- The `high`-confidence trend flag constraint was tested and rejects a flag
  without both windows confirmed — principle 5 enforced in the schema.
- The model was run end to end against live FPL and the vaastav archive.
- The password gate was tested for unauthenticated access, forged cookies,
  wrong passwords and an open-redirect attempt via `next=//evil.com`.

`ep_next` from the FPL API was tried as a calibration target and **rejected**:
pre-season it takes only 26 distinct values across 592 players, is capped at 4.0,
and puts Haaland and Raya on the same figure. It is a placeholder, not a
projection, and tuning toward it would have fitted noise.
