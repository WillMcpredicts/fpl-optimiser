"""Resolving a team strength rating, with an honest fallback chain.

Pre-season this is not a solved problem. FPL-Core-Insights ships a `teams.csv`
for the new season but leaves `elo` blank until matches are played, and the FPL
API's own strength ratings collapse to a coarse 1-5 scale until the season
starts. So the rating is resolved in order of preference, and every team records
WHICH source it came from -- a projection resting on a promoted-side guess
should not look as solid as one resting on 38 games of Elo.

    1. This season's Elo, once FPL-Core-Insights populates it.
    2. Last season's final Elo, carried forward by team `code`. Codes are stable
       across seasons; ids are not.
    3. A promoted-side prior for clubs with no top-flight rating, nudged by
       FPL's coarse strength rating.
"""
from __future__ import annotations

from common import get_csv, log, to_float, to_int
from config import CORE_INSIGHTS_RAW, core_insights_season

# Where a newly-promoted side typically enters the Premier League. Deliberately
# below the weakest returning team: promoted sides are usually the bottom of the
# division on day one. Replaced by real Elo as soon as they have played.
PROMOTED_ELO_PRIOR = 1690.0
# FPL's 1-5 strength scale, as an adjustment either side of that prior.
STRENGTH_NUDGE = {1: -40.0, 2: -20.0, 3: 0.0, 4: 20.0, 5: 40.0}

SOURCE_CURRENT = "current_season_elo"
SOURCE_CARRIED = "carried_from_last_season"
SOURCE_PROMOTED = "promoted_side_prior"


def previous_season(season: str) -> str:
    """'2026-27' -> '2025-26'."""
    start, end = season.split("-")
    return f"{int(start) - 1}-{int(end) - 1:02d}"


def _elo_from_repo(season: str, key: str) -> dict[int, float]:
    """Newest populated teams.csv for a season, keyed by `key` ('id' or 'code')."""
    ci = core_insights_season(season)
    for gw in range(38, 0, -1):
        try:
            rows = get_csv(
                f"{CORE_INSIGHTS_RAW}/{ci}/By%20Gameweek/GW{gw}/teams.csv",
                required=False,
            )
        except Exception as exc:  # noqa: BLE001 - a missing week is not fatal
            log(f"  elo: GW{gw} unavailable ({exc})")
            continue
        found = {
            to_int(r[key]): to_float(r["elo"])
            for r in rows
            if r.get(key) and (r.get("elo") or "").strip()
        }
        if found:
            log(f"  elo: {season} GW{gw} gave {len(found)} teams (by {key})")
            return found
    return {}


def resolve(season: str, boot_teams: list[dict]) -> tuple[dict[int, float], dict[int, str]]:
    """Elo per FPL team id for `season`, plus the source used for each."""
    elo: dict[int, float] = {}
    source: dict[int, str] = {}

    current = _elo_from_repo(season, "id")
    for team_id, value in current.items():
        elo[team_id] = value
        source[team_id] = SOURCE_CURRENT

    missing = [t for t in boot_teams if t["id"] not in elo]
    if missing:
        prev = previous_season(season)
        carried = _elo_from_repo(prev, "code")
        for t in missing:
            value = carried.get(t["code"])
            if value is not None:
                elo[t["id"]] = value
                source[t["id"]] = SOURCE_CARRIED

    still_missing = [t for t in boot_teams if t["id"] not in elo]
    for t in still_missing:
        nudge = STRENGTH_NUDGE.get(t.get("strength_overall_home") or 3, 0.0)
        elo[t["id"]] = PROMOTED_ELO_PRIOR + nudge
        source[t["id"]] = SOURCE_PROMOTED

    if still_missing:
        names = ", ".join(t["short_name"] for t in still_missing)
        log(f"  elo: promoted-side prior used for {names}")

    counts: dict[str, int] = {}
    for s in source.values():
        counts[s] = counts.get(s, 0) + 1
    log(f"  elo resolved: {counts}")
    return elo, source
