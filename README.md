# FPL Optimiser

Personal-use tool for scoring an FPL squad and planning transfers. Next.js on
Vercel, Supabase Postgres, Python ingestion on GitHub Actions.

Separate from the Prem Predictor prediction-league app, which lives in its own
repo and its own Supabase project.

## Status

| Phase | Scope | State |
|---|---|---|
| 1 | FPL + historical ingestion, predicted points table | **Done, live on Supabase** |
| 2 | Trend engine, backtest, sign-off gate | **Done. Backtested, gate stays OFF by decision** |
| 3 | Squad import, transfer planner, full UI | **Done** |
| 4 | Automated ingestion schedule | **Done** |

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

**The trend engine failed its own backtest.** See "Backtest result" below. The
gate in `trend_engine_gate` is `enabled = false` and trend adjustments are zero.

**The season has not started.** No gameweeks are played, so every rate comes from
2025/26 priors. The trend engine's minimum sample floor and persistence check
mean no trend can legitimately be flagged until roughly GW9.

**Elo is unresolved pre-season.** FPL-Core-Insights ships the 2026/27 `teams.csv`
with `elo` blank, the direct ClubElo API was unreachable when tested, and the FPL
API collapses to a coarse 1-5 strength scale until the season starts. `ingest/elo.py`
resolves it in order — this season's Elo, then last season's carried forward by
`code`, then a promoted-side prior — and records which source each team used, so
a projection resting on a guess does not look as solid as one resting on 38 games.

## The Supabase project

`fpl-optimiser`, ref `vzaieavyivsbgfsxzdbo`, region eu-west-2 (London), Postgres 17.
Separate from the prediction league's project. Migrations 0001-0005 are applied.

Two things worth knowing about applying migrations through the Management API:
PostgREST caches the schema, so a fresh column needs
`notify pgrst, 'reload schema';` before an upsert can see it; and the database
password is not recoverable, only resettable, from Settings -> Database.

## Security note

Next.js is pinned at 16.3.1 or later deliberately. Version 15.1.6 carries
CVE-2025-29927, an authorization bypass where a crafted `x-middleware-subrequest`
header skips middleware entirely -- and this app's password gate *is* middleware,
so the gate was bypassable. Vercel refuses to deploy the vulnerable version,
which is how it was caught. Do not downgrade below 16.3.1.

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

## Transfer economy

One free transfer a week, up to five bankable, -4 points per extra transfer.
Confirmed against the live game settings (`max_extra_free_transfers = 4`).

The planner answers two separate questions and keeps them separate:

**Each ranked row** is one transfer taken on its own, so its hit is simply
whether a free transfer is available. Ranking rows and charging a cumulative hit
down the list would be nonsense: three swaps all bringing in the same striker
cannot be taken together, and pricing them as if they could invents a transfer
you could never make.

**The plan** is the executable version -- a greedy, non-conflicting sequence
that tracks the bank and charges -4 once the free transfers run out. It then
reports the *depth* whose cumulative net is highest, which is usually one
transfer rather than the longest sequence available. In testing, a four-move
plan grossing +14.15 netted +2.15 after hits, against +6.34 for the single best
move -- so the answer was "make one transfer", and the tool says so.

Swaps are filtered for affordability from sale value plus bank, and for the
three-per-club limit, which is easy to forget and invalidates a team.

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
.github/workflows/
  ingest.yml    Scheduled pipeline, 06:15 and 17:45 UTC
  checks.yml    Typecheck, build, and the unit suite on every push
```

## Where it runs

- App: https://fpl-optimiser-rosy.vercel.app (private Vercel project, password gated)
- Code: https://github.com/WillMcpredicts/fpl-optimiser (private)
- Database: Supabase `fpl-optimiser`, ref `vzaieavyivsbgfsxzdbo`, eu-west-2

### Known blocker: GitHub-hosted runners

The scheduled workflow is registered and correct, but every run so far ends with
`The job was not acquired by Runner of type hosted even after multiple attempts`
-- GitHub never allocates a machine, and the job is cancelled after ~15 minutes.
No run on this account has ever succeeded. This is account-level runner
availability, not the workflow: the YAML parses, the run queues, and no step
executes.

Three ways out, in order of least effort:

1. Make the repo public. Public repositories get free unlimited hosted runners.
   Nothing secret is in the code -- credentials live in Actions secrets and
   Vercel env vars, neither of which becomes public.
2. Add a payment method / complete verification on the GitHub account, which is
   what usually unblocks hosted runners on a new free account.
3. Run the pipeline locally on a schedule (`launchd` on macOS) against the same
   Supabase project. Same result, no GitHub involvement.

Until one of those, run it by hand -- it takes about a minute:

```bash
cd ~/fpl-optimiser/ingest && ../.venv/bin/python run.py all
```

## Automation

`ingest.yml` runs twice daily. Prices settle just after 01:30 UK and team news
lands through the morning, so the early run keeps the table current; the evening
run catches late team news and, after matchdays, finished-gameweek stats.

Needs two repository secrets, `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY`,
and optionally a `FPL_SEASON` variable. The final step reads `ingest_runs` back
and fails the job if any step failed, so a broken scrape is visible rather than
silently serving stale numbers.

The historical backfill is deliberately excluded from the routine run: three
seasons of player-gameweeks do not change, and re-fetching 87,000 rows twice a
day would be waste. Use `run.py full` for a first run or after a schema change.

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


## Backtest result (principle 6)

Walk-forward over all of 2025-26: at each gameweek, flags are built from only the
gameweeks already played, then scored against what actually happened over the
next three. Two predictors of the forward rate are compared — the league mean
("assume average") and the team's shrunk rate ("assume the pattern continues").

| Tier | Flags | Improvement vs baseline | Hit rate |
|---|---|---|---|
| high | 7 | +10.9% | 0.86 |
| medium | 19 | **−184%** | 0.63 |
| watch | 300 | −14.6% | 0.56 |

**Verdict: trends are not wired into predicted points.** Seven high-confidence
flags in a whole season is too few to conclude anything, and medium-confidence
flags make forward predictions substantially worse than assuming league average.

### Why — split-half reliability

A team's rate over GW1-19 against its rate over GW20-38, ~231 shots per team
per half. If a stat is a real, persistent team property the halves correlate.

| Stat | r | Reading |
|---|---|---|
| Own headed xG share | **0.73** | stable |
| Own set-piece xG share | **0.51** | stable |
| xG per shot conceded | 0.39 | weak |
| Headed xG conceded per shot faced | 0.34 | weak |
| Headed shots conceded per shot faced | 0.28 | weak |
| Set-piece shots conceded per shot faced | 0.16 | noise |
| Fast-break shots conceded per shot faced | 0.10 | noise |
| Left-flank shots conceded per shot faced | 0.01 | noise |
| Box shots conceded per shot faced | **−0.31** | noise |

**Attacking patterns persist; defensive ones do not.** How a team attacks is a
coached, deliberate style. How it concedes by body part or zone is mostly a
property of whichever opponents it happened to face. The brief's central example
— a team conceding disproportionately from a specific pattern — is the half that
does not survive contact with the data.

### What the safeguards were worth

Running the same backtest without empirical Bayes shrinkage produces **148
"high-confidence" flags** with a hit rate of 0.52 and forward predictions
**7% worse** than assuming league average. With shrinkage, almost none survive.

That is the entire value of principle 3, measured: it is the difference between a
tool that confidently recommends a hundred and fifty bad transfers a season and
one that says it does not know.

### Two corrections found while backtesting

- **Sampling variance was assumed Bernoulli.** For xG-valued stats that is wrong
  and made genuinely stable stats look like noise. It is now measured from the
  actual per-event spread.
- **The z denominator was the observed spread.** A shrunk estimate must be
  measured against the spread of *true* team rates; the observed spread is
  inflated by the very sampling noise the shrinkage already removed, so dividing
  by it penalised the same noise twice.
