"""Entry point for the ingestion pipeline.

    python ingest/run.py all       # live FPL, predictions, transfer plan
    python ingest/run.py full      # 'all' plus the one-off historical backfill
    python ingest/run.py history   # vaastav backfill (once per past season)
    python ingest/run.py fpl       # live FPL only
    python ingest/run.py predict   # recompute predicted points
    python ingest/run.py sync      # pull the last locked squad from FPL
    python ingest/run.py plan      # recompute transfer suggestions
    python ingest/run.py optimise  # best reachable squad (MILP)
    python ingest/run.py chips     # Bench Boost and Triple Captain timing
    python ingest/run.py shots     # FPL-Core-Insights shot data
    python ingest/run.py trends    # rate stats and trend flags for the live season
    python ingest/run.py backtest  # re-run the trend backtest

`all` is the routine refresh: live FPL data, predictions, shot-level events for
the current season, trend rates and flags, the transfer plan and the optimiser.
Trends accumulate as the season plays, but stay out of scoring until the gate in
`trend_engine_gate` is switched on. The historical backfill is deliberately not part
of it: three seasons of player-gameweeks do not change, and re-fetching ~87,000
rows on every run would be pure waste.
"""
from __future__ import annotations

import sys

from common import log
from config import CURRENT_SEASON

# Live trends are built for the season being played. The backtest needs a
# COMPLETED season, so it stays pointed at the last finished one -- validating a
# model against a season still in progress would be measuring nothing.
BACKTEST_SEASON = "2025-26"


def main() -> int:
    step = sys.argv[1] if len(sys.argv) > 1 else "all"
    known = {
        "all", "full", "history", "fpl", "predict", "plan",
        "optimise", "chips", "shots", "trends", "backtest", "sync",
    }
    if step not in known:
        print(__doc__)
        return 2

    if step in ("full", "history"):
        import history

        history.main()

    if step in ("all", "full", "fpl"):
        import fpl

        fpl.main(CURRENT_SEASON)

    if step in ("all", "full", "predict"):
        import model

        model.main(CURRENT_SEASON)

    if step in ("all", "full", "shots"):
        import shots

        # Shot-level data for the live season, so trends accumulate as it plays.
        shots.main(CURRENT_SEASON)
        if step == "full":
            shots.main(BACKTEST_SEASON)

    if step in ("all", "full", "trends"):
        import trends

        trends.main(CURRENT_SEASON)
        if step == "full":
            trends.main(BACKTEST_SEASON)

    if step in ("full", "backtest"):
        import backtest

        sys.argv = ["backtest.py", BACKTEST_SEASON]
        backtest.main()

    if step in ("all", "full", "sync"):
        import squad_sync

        # Before planning: a plan built on last week's squad is worthless.
        squad_sync.main(CURRENT_SEASON)

    if step in ("all", "full", "plan"):
        import planner

        try:
            planner.main()
        except RuntimeError as exc:
            # No squad imported yet is a normal state, not a pipeline failure.
            log(f"[planner] skipped: {exc}")

    if step in ("all", "full", "optimise"):
        import optimiser

        optimiser.main()

    if step in ("all", "full", "chips"):
        import chips

        chips.main()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
