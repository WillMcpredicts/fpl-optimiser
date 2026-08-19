"""Entry point for the ingestion pipeline.

    python ingest/run.py all        # history (once) + live FPL + predictions
    python ingest/run.py fpl        # live FPL only
    python ingest/run.py history    # vaastav backfill only
    python ingest/run.py predict    # recompute predicted points
"""
from __future__ import annotations

import sys

import fpl
import history
import model
from config import CURRENT_SEASON


def main() -> int:
    step = sys.argv[1] if len(sys.argv) > 1 else "all"
    if step in ("all", "history"):
        history.main()
    if step in ("all", "fpl"):
        fpl.main(CURRENT_SEASON)
    if step in ("all", "predict"):
        model.main(CURRENT_SEASON)
    if step not in ("all", "history", "fpl", "predict"):
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
