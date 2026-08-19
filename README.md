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

## The optimiser

Solved exactly as a mixed-integer program with CBC, not chosen greedily. Greedy
selection fails here because the budget, the three-per-club cap and the formation
rules interact -- the best squad is not the best players picked one at a time.

Two modelling choices that matter more than the solver:

**The objective is the starting XI, not the squad.** Bench points do not score,
so money spent there is wasted. Told to maximise all fifteen, the model buys a
strong bench and a weaker eleven. Told to maximise the XI, it buys the cheapest
legal bench it can find and spends the difference on the team that plays.

**The XI is chosen per gameweek.** You can reshuffle your eleven every week
without a transfer, so a player who blanks in one gameweek should be benched that
week rather than dragging down the squad's value across the horizon. Captaincy is
included and also varies by gameweek, because it doubles real points.

`reachable` mode then solves the same problem constrained to your actual squad,
bank and sale values, once for each transfer count from 0 to 5, and reports the
net after hits. That is the number that answers "is this transfer worth it".

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

## Set pieces and penalties

Penalty order, direct free-kick order and corner order are ingested. Penalty
duty only adjusts a score where it has CHANGED, and the reason is measured:
first-choice takers out-scored their own prior rate by just +0.05 points per
appearance, and the best-fitting blanket bonus was zero. A taker's history
already contains the penalties they took, so a bonus on top double-counts.

The real gap is a change of duty. 92 penalties across 380 matches in 2025-26 at
82% conversion is 0.121 per team-match, so a newly-appointed taker is worth
about +0.51 pts/90 (MID) or +0.41 (FWD) that their history does not show. Twelve
players gained first-choice duty for 2026-27 and one lost it.

## Chips

Bench Boost is valued as what the bench actually projects that week; Triple
Captain as one extra copy of the best single score. Wildcard and Free Hit are
deliberately not planned: their value depends on what you would transfer to,
which is the optimiser's job.

## Team weaknesses by role

Tested and rejected. "Left wingers score more against Fulham" needs role within
position, which FPL does not publish, so role was derived from where each player
actually shoots. Split-half reliability came out at 0.41 (left), 0.41 (central)
and 0.30 (right) -- all weaker than the position-based version already live.
Classification is also thin: 219 of 274 players read as "central" because
wingers still shoot from central areas.

## The trend that does move a score

How generous each team is to each position, in FPL points. Face a dominant
possession side and your defenders spend the match clearing and blocking, so
their defensive-contribution points rise whatever the score. Structural and
repeatable, unlike the shot patterns below.

Validated the hard way, in `ingest/opponent_backtest.py`: measured INCREMENTALLY
over the Elo fixture adjustment, because a strong team both concedes few points
and carries a high Elo -- test it naively and you re-discover fixture difficulty
and flatter the result. Damping tuned on GW10-24 of 2025-26, scored on GW25-38.

| Position | Player-GWs | Gain over the fixture adjustment | Used |
|---|---|---|---|
| GKP | 259 | +0.54% | no -- does not survive the summer (r = 0.01) |
| DEF | 1369 | +0.55% | yes, seeded 30% from last season |
| MID | 1786 | +0.54% | yes, seeded 60% from last season |
| FWD | 498 | -0.09% | no -- effect is negative |

The gain is uniform across three independent position groups, which noise does
not do. Damped to 0.4 and capped at 15%. For scale, the Elo adjustment itself is
worth 2.1% on the same test -- this is a refinement, not the engine.

## Why shot-pattern trends still do not move a score

The obvious idea is that if a defence concedes headers, a header-scoring attacker
should get an uplift against them. It has two halves and they are not equally
true.

The attacking half is real: a team's headed share of its own chances persists
across a season (r = 0.73). The defensive half mostly is not (r = 0.28), because
how a side concedes by body part is largely decided by who it happened to play --
face three crossing teams and you look weak in the air.

`ingest/matchup_test.py` tests the combination directly rather than relying on
that. Walk-forward over 660 team-matches, the interaction genuinely correlates
better with what happened (r = 0.166 vs 0.138 for the attacker alone, t = 4.31 --
not chance). But even at its best tuning it beats attacker-alone by 0.67% and is
still marginally worse than assuming the league average. The tuning is in-sample,
so the true figure is lower.

Detectable is not useful. The half that is real is already counted anyway: a
player who scores headers has those headers in their own xG history.

### Why the repository is public

While it was private, every Actions run ended with `The job was not acquired by
Runner of type hosted even after multiple attempts` -- GitHub allocated no
machine and cancelled the job after ~15 minutes. Public repositories get free
unlimited hosted runners, and making it public fixed it immediately. Nothing
secret is in the code: credentials live in Actions secrets and Vercel
environment variables, neither of which is exposed by public source.

To run the pipeline by hand instead, it takes about a minute:

```bash
cd ~/fpl-optimiser/ingest && ../.venv/bin/python run.py all
```

## What it does, and what it does not

1. **Rate the current team** — yes. Every player carries next-GW and 3-GW
   projections, points per £m, and a percentile against same-position players
   within £0.5m. The squad as a whole is scored against the best possible
   £100.0m team, so "how good is this" has a number.
2. **Surface hidden trends** — **no, and deliberately.** The trend engine is
   built, backtested and switched off, because it did not predict forward
   performance. See "Why trends still do not move a score".
3. **Recommend improvements** — yes. The optimiser solves for the best reachable
   squad at every transfer count and reports the net after hits.
4. **Build live trends through the season** — the plumbing now runs on every
   routine refresh, so shot-level events and rate stats accumulate from GW1
   onward. They still do not move a score: the gate in `trend_engine_gate` stays
   off until a backtest on THIS season justifies opening it.

## What refreshes on its own

Everything except the squad, and the squad now too once a manager id is set.

| | Automatic? |
|---|---|
| Prices, injuries, availability flags | yes |
| Finished-gameweek player stats | yes |
| Projection window rolling forward | yes — projects the next unfinished gameweeks |
| Shot data and trend rates for the live season | yes |
| Transfer plan, optimiser, chip timing | yes |
| **Your squad** | only with `FPL_MANAGER_ID` set |

Set `FPL_MANAGER_ID` as a repository variable and `run.py sync` pulls the last
locked squad after each gameweek, before the planner runs. Without it the squad
stays wherever it was last entered by hand, and every recommendation is built on
that -- which goes stale the moment a transfer is made.

A squad entered by hand for a later gameweek is never overwritten: manual entry
is the only way to record a team before a deadline, so it is always the more
current statement of intent.

## How accurate is it, really?

`ingest/model_backtest.py` replays the whole model over a completed season,
gameweek by gameweek, rebuilding every rate from only the football played
before each one. Measured against the honest bar: a player's own points per
game to date, which is what a sensible person would guess.

Over 13,503 player-gameweeks in 2025-26:

| Predictor | MAE | Correlation |
|---|---|---|
| League average by position | 1.462 | 0.079 |
| Own points per game | 0.958 | 0.530 |
| This model | 1.021 | 0.499 |

**In aggregate the model loses to points-per-game by 6.5%.** That is worth
stating plainly rather than burying. But the aggregate is dominated by players
who never featured -- 66% of the observations -- and you never pick those:

| | n | Actual | Model MAE | PPG MAE |
|---|---|---|---|---|
| Featured | 4,580 | 3.00 | **2.012** | 2.069 |
| Did not play | 8,923 | 0.00 | 0.512 | **0.388** |

Among players who actually played, the model is better. And where selection
happens -- the top of the ranking -- it is clearly better:

| Top N by projection | Model | Own PPG |
|---|---|---|
| 10 | **4.05** | 3.90 |
| 25 | **3.69** | 3.53 |
| 50 | 3.25 | **3.31** |
| 100 | 2.74 | **2.93** |

So: better at picking a captain or a transfer target, worse at guessing an
arbitrary squad player's score. That is the right way round for the job, but it
is not "more accurate than the simple approach" and should not be sold as such.

The backtest also found and fixed a real bias: appearance probabilities came out
systematically high, predicting 25.2 minutes a player against 21.8 actual, with
the excess in the 0.2-0.5 band. Ordering was already sound, so it needed a
calibration curve rather than a rethink -- `APPEARANCE_CALIBRATION` in rates.py.
That alone took overall MAE from 1.139 to 1.021 and lifted top-10 selection from
3.95 to 4.05.

## Why the bench is not free

Only eleven play, so the objective is the starting XI -- but treating the bench
as worthless is wrong, and the data says so twice.

FPL auto-substitutes when a starter records no minutes. Measured on 2025-26, a
regular starter blanks **14.1%** of the time, so across an XI of eleven the bench
slots are used with probability 0.81, 0.47 and 0.19 -- about 1.48 substitutions a
gameweek. The optimiser weights bench points by 0.37, the average chance any
given bench player features.

Before that weighting it bought four players at £4.0-4.5m who never appeared,
spending £17.5m on nothing to gain **+2.1 XI points over six gameweeks (0.7%)**.
Against roughly nine auto-substitution events in the same period, each one
landing on a player worth about a point instead of four or five, that trade is
clearly bad.

With the weighting the optimal squad has no passengers -- which is exactly what
the retrospective found for a completed season, from entirely separate data.

## What last season's perfect squad looked like

`ingest/retrospective.py` solves the same problem with hindsight: the best static
£100m squad for a completed season, no transfers, priced at what you would
actually have paid in August. Not a benchmark -- the perfect squad is unknowable
in advance -- but the STRUCTURE transfers even though the players do not.

For 2025-26 the ceiling was **3,098 points from £99.5m**, and three things stand
out:

**No bench fodder at all.** Every one of the fifteen started at least a quarter
of the season; the cheapest was £4.5m and scored 143. Over a full season with no
transfers, rotation and injuries mean every slot gets used, so a £4.0m
non-playing enabler is wasted money. Note this contradicts the forward-looking
optimiser, which DOES buy cheap fodder -- correctly, because over a six-gameweek
horizon a fourth-choice bench player genuinely never plays. The two answers
differ because the questions differ.

**Only two players at £9.0m or more.** Haaland at £14.0m returned 239 points but
17.1 per £m, the worst value in the squad, and was still worth buying. Everything
else sat between £4.5m and £7.5m.

**Defenders were the best value, forwards the worst.** Defence took 26.6% of the
budget and returned 29.3% of the points; forwards took 27.6% and returned 19.3%.
By price band, cheap defenders delivered ~18-19 points per £m against ~15-16 for
midfielders and forwards at any price. DefCon is the reason.

## The weekly cycle

What the tool answers each week, and where:

| Decision | Where |
|---|---|
| Who to transfer, and whether to take a hit | Optimiser |
| Who to captain | Optimiser, per gameweek |
| Who to start and who to bench | Squad, with a gameweek selector |
| Whether to play a chip | Optimiser |
| Who is worth buying | Predicted points, three views |

The starting XI is chosen for ONE gameweek, not the horizon total. That
distinction matters: a player with a blank this week and a good run later should
still be benched now, and ranking on a six-gameweek total gets that backwards.

Known gaps, in rough order of how much they would cost you:

- **Predicted lineups.** No free, reliable source. Minutes are modelled from
  start history, depth chart and FPL's own availability flag, which is the best
  available substitute but will not catch a surprise rotation.
- **European and cup congestion.** The data identifies competitions but nothing
  models "played Thursday in Europe, likely rested Sunday".
- **Bench order.** Auto-substitutions follow bench order and it is not modelled.
- **Double and blank gameweeks.** Multiple fixtures per gameweek are handled
  correctly in the maths but never flagged in the UI. None are scheduled yet.

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
