"""Entry point for the ingestion pipeline.

    python ingest/run.py all       # live FPL, predictions, transfer plan
    python ingest/run.py full      # 'all' plus the one-off historical backfill
    python ingest/run.py history   # vaastav backfill (once per past season)
    python ingest/run.py fpl       # live FPL only
    python ingest/run.py predict   # recompute predicted points
    python ingest/run.py plan      # recompute transfer suggestions
    python ingest/run.py shots     # FPL-Core-Insights shot data
    python ingest/run.py trends    # rate stats and trend flags
    python ingest/run.py backtest  # re-run the trend backtest

`all` is the routine refresh. The historical backfill is deliberately not part
of it: three seasons of player-gameweeks do not change, and re-fetching ~87,000
rows on every run would be pure waste.
"""
from __future__ import annotations

import sys

from common import log
from config import CURRENT_SEASON

TREND_SEASON = "2025-26"


def main() -> int:
    step = sys.argv[1] if len(sys.argv) > 1 else "all"
    known = {"all", "full", "history", "fpl", "predict", "plan", "shots", "trends", "backtest"}
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

    if step in ("full", "shots"):
        import shots

        shots.main(TREND_SEASON)

    if step in ("full", "trends"):
        import trends

        trends.main(TREND_SEASON)

    if step in ("full", "backtest"):
        import backtest

        sys.argv = ["backtest.py", TREND_SEASON]
        backtest.main()

    if step in ("all", "full", "plan"):
        import planner

        try:
            planner.main()
        except RuntimeError as exc:
            # No squad imported yet is a normal state, not a pipeline failure.
            log(f"[planner] skipped: {exc}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
