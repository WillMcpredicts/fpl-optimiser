"""The trend engine.

Implements section 3 in order, and each safeguard is here because without it the
tool would confidently recommend bad transfers:

  1. Rate, not count      -- every stat is a numerator over the opportunities
                             that produced it, never a raw total.
  2. League-relative      -- scored as a z against the spread of all 20 clubs.
  3. Empirical Bayes      -- shrunk toward the league rate, with the shrinkage
                             constant ESTIMATED FROM THE DATA by method of
                             moments, not picked by hand.
  4. Minimum sample floor -- under MIN_EVENTS opportunities a stat is computed
                             and stored but never promoted to a trend.
  5. Persistence          -- 'high' requires the pattern in two non-overlapping
                             windows, in the same direction.
  7. Bounded influence    -- the points multiplier is capped and only non-zero
                             at medium or high confidence.

Nothing here writes to predicted points. The predictor reads trend_flags, and
only when the gate in trend_engine_gate has been switched on after a backtest.
"""
from __future__ import annotations

import statistics
from collections import defaultdict
from dataclasses import dataclass
from typing import Callable

# Principle 4. Five relevant events is the floor for promotion to a trend.
MIN_EVENTS = 5
# Principle 5. Window length in matches, and the gap that makes them disjoint.
WINDOW = 4
# Strength needed in the primary window, and the weaker bar for confirmation.
Z_STRONG = 1.5
Z_CONFIRM = 1.0
# Principle 7. Hard ceiling on trend influence, before the gate's own cap.
MAX_MULTIPLIER = 0.20
# Upper bound on the shrinkage constant: past this, a stat is pure noise.
SHRINKAGE_CEILING = 500.0

SET_PIECE_SITUATIONS = {"corner", "free-kick", "set-piece", "throw-in-set-piece"}
BOX_ZONES = ("six_yard", "penalty_area")


@dataclass(frozen=True)
class StatDef:
    """A single opportunity-normalised statistic.

    `numerator` and `denominator` are both measured over the shots a team faced
    (conceded stats) or took (attacking stats). The denominator IS the sample
    size -- that is what makes the rate comparable between a team that has faced
    120 shots and one that has faced 12.
    """

    key: str
    label: str
    conceded: bool
    numerator: Callable[[dict], float]
    denominator: Callable[[dict], float]
    higher_is_vulnerable: bool = True


def _is_header(s: dict) -> bool:
    return (s.get("body_part") or "") == "head"


def _is_set_piece(s: dict) -> bool:
    return (s.get("situation") or "") in SET_PIECE_SITUATIONS


def _in_box(s: dict) -> bool:
    return (s.get("zone") or "").startswith(BOX_ZONES)


def _flank(s: dict, side: str) -> bool:
    return (s.get("zone") or "").endswith(side)


STAT_DEFS: list[StatDef] = [
    StatDef(
        "head_shots_conceded_per_shot_faced",
        "Headed shots allowed, per shot faced",
        True,
        lambda s: 1.0 if _is_header(s) else 0.0,
        lambda s: 1.0,
    ),
    StatDef(
        "head_xg_conceded_per_shot_faced",
        "Headed xG allowed, per shot faced",
        True,
        lambda s: (s.get("xg") or 0.0) if _is_header(s) else 0.0,
        lambda s: 1.0,
    ),
    StatDef(
        "setpiece_shots_conceded_per_shot_faced",
        "Set-piece shots allowed, per shot faced",
        True,
        lambda s: 1.0 if _is_set_piece(s) else 0.0,
        lambda s: 1.0,
    ),
    StatDef(
        "setpiece_xg_conceded_per_shot_faced",
        "Set-piece xG allowed, per shot faced",
        True,
        lambda s: (s.get("xg") or 0.0) if _is_set_piece(s) else 0.0,
        lambda s: 1.0,
    ),
    StatDef(
        "box_shots_conceded_per_shot_faced",
        "Shots allowed inside the box, per shot faced",
        True,
        lambda s: 1.0 if _in_box(s) else 0.0,
        lambda s: 1.0,
    ),
    StatDef(
        "fastbreak_shots_conceded_per_shot_faced",
        "Fast-break shots allowed, per shot faced",
        True,
        lambda s: 1.0 if (s.get("situation") or "") == "fast-break" else 0.0,
        lambda s: 1.0,
    ),
    StatDef(
        "left_flank_shots_conceded_per_shot_faced",
        "Shots allowed from their left, per shot faced",
        True,
        lambda s: 1.0 if _flank(s, "left") else 0.0,
        lambda s: 1.0,
    ),
    StatDef(
        "right_flank_shots_conceded_per_shot_faced",
        "Shots allowed from their right, per shot faced",
        True,
        lambda s: 1.0 if _flank(s, "right") else 0.0,
        lambda s: 1.0,
    ),
    StatDef(
        "xg_per_shot_conceded",
        "Quality of chance allowed, xG per shot faced",
        True,
        lambda s: s.get("xg") or 0.0,
        lambda s: 1.0,
    ),
    StatDef(
        "head_xg_share_for",
        "Own headed xG, per shot taken",
        False,
        lambda s: (s.get("xg") or 0.0) if _is_header(s) else 0.0,
        lambda s: 1.0,
        higher_is_vulnerable=False,
    ),
    StatDef(
        "setpiece_xg_share_for",
        "Own set-piece xG, per shot taken",
        False,
        lambda s: (s.get("xg") or 0.0) if _is_set_piece(s) else 0.0,
        lambda s: 1.0,
        higher_is_vulnerable=False,
    ),
]

STAT_BY_KEY = {s.key: s for s in STAT_DEFS}


def aggregate(events: list[dict], stat: StatDef) -> dict[int, tuple[float, float]]:
    """(numerator, denominator) per team for one stat over the given events."""
    totals: dict[int, list[float]] = defaultdict(lambda: [0.0, 0.0])
    key = "opponent_id" if stat.conceded else "team_id"
    for s in events:
        team = s.get(key)
        if team is None:
            continue
        t = totals[team]
        t[0] += stat.numerator(s)
        t[1] += stat.denominator(s)
    return {team: (n, d) for team, (n, d) in totals.items()}


def per_event_values(events: list[dict], stat: StatDef) -> dict[int, list[float]]:
    """Each team's individual per-event numerator values.

    Needed because the sampling variance of a rate depends on the spread of the
    thing being averaged. A count-based stat is Bernoulli; an xG-based one is
    not, and assuming otherwise makes every xG stat look like pure noise.
    """
    out: dict[int, list[float]] = defaultdict(list)
    key = "opponent_id" if stat.conceded else "team_id"
    for s in events:
        team = s.get(key)
        if team is not None:
            out[team].append(stat.numerator(s))
    return out


def estimate_shrinkage(
    pairs: dict[int, tuple[float, float]],
    pooled: float,
    values_by_team: dict[int, list[float]] | None = None,
) -> tuple[float, float]:
    """Empirical Bayes shrinkage constant, by method of moments.

    Returns k in the same units as the denominator: the posterior mean is
    (numerator + k * pooled) / (denominator + k), so k is literally "how many
    league-average opportunities to add before believing a team's own rate".

    k = within-team variance / between-team variance, the standard hierarchical
    result. Within-team variance is measured from the actual per-event values
    rather than assumed Bernoulli -- an xG-valued stat has a very different
    spread from a 0/1 count, and using p(1-p) for it understates real
    between-team differences badly enough to suppress every genuine trend.

    When between-team variance is indistinguishable from sampling noise, every
    apparent difference is chance, and k goes large so nothing escapes the mean.
    """
    usable = [(n, d) for n, d in pairs.values() if d > 0]
    if len(usable) < 3:
        return SHRINKAGE_CEILING, 0.0

    rates = [n / d for n, d in usable]
    observed_var = statistics.pvariance(rates)

    if values_by_team:
        pooled_values = [v for vals in values_by_team.values() for v in vals]
        within_var = statistics.pvariance(pooled_values) if len(pooled_values) > 1 else 0.0
    elif 0 < pooled < 1:
        within_var = pooled * (1 - pooled)
    else:
        return SHRINKAGE_CEILING, 0.0

    if within_var <= 0:
        return SHRINKAGE_CEILING, 0.0

    # Variance you would see even if every team were identical.
    sampling_var = within_var * statistics.mean(1.0 / d for _, d in usable)
    between_var = observed_var - sampling_var
    if between_var <= 1e-12:
        return SHRINKAGE_CEILING, 0.0  # all apparent spread is noise; shrink hard

    k = max(1.0, min(SHRINKAGE_CEILING, within_var / between_var))
    return k, between_var ** 0.5


def compute_window(
    events: list[dict], stat: StatDef, as_of_gw: int, window_label: str
) -> list[dict]:
    """team_rate_stats rows for one stat over one window."""
    pairs = aggregate(events, stat)
    if not pairs:
        return []

    total_n = sum(n for n, _ in pairs.values())
    total_d = sum(d for _, d in pairs.values())
    pooled = total_n / total_d if total_d else 0.0

    rates = [n / d for n, d in pairs.values() if d > 0]
    stdev = statistics.pstdev(rates) if len(rates) > 1 else 0.0
    k, between_stdev = estimate_shrinkage(pairs, pooled, per_event_values(events, stat))

    rows = []
    for team, (n, d) in pairs.items():
        rate = n / d if d else 0.0
        shrunk = (n + k * pooled) / (d + k) if (d + k) else pooled
        rows.append(
            {
                "as_of_gw": as_of_gw,
                "team_id": team,
                "window_label": window_label,
                "stat_type": stat.key,
                "events": round(n, 4),
                "opportunities": round(d, 4),
                "rate": round(rate, 6),
                "sample_size": int(d),
                "league_mean": round(pooled, 6),
                "league_stdev": round(stdev, 6),
                # Raw z: how unusual the OBSERVED rate looks, noise included.
                "z_score": round((rate - pooled) / stdev, 4) if stdev else None,
                "shrunk_rate": round(shrunk, 6),
                # The z that decides promotion. The shrunk rate is our estimate
                # of the team's TRUE rate, so it is measured against the spread
                # of true rates (between-team stdev), not the observed spread --
                # the latter is inflated by sampling noise, and dividing a
                # shrunk numerator by it penalises the same noise twice.
                "shrunk_z": (
                    round((shrunk - pooled) / between_stdev, 4) if between_stdev else None
                ),
                "between_stdev": round(between_stdev, 6),
                "shrinkage_k": round(k, 2),
                # Principle 4: recorded, but this is what blocks promotion.
                "meets_sample_floor": d >= MIN_EVENTS,
            }
        )
    return rows


def windows_for(as_of_gw: int) -> dict[str, range]:
    """Two non-overlapping windows ending before `as_of_gw` (principle 5)."""
    recent_start = max(1, as_of_gw - WINDOW)
    previous_start = max(1, as_of_gw - 2 * WINDOW)
    return {
        "last4": range(recent_start, as_of_gw),
        "prev4": range(previous_start, recent_start),
    }


def build_rate_stats(events_by_gw: dict[int, list[dict]], as_of_gw: int) -> list[dict]:
    """All rate rows for every stat and both windows, as of a gameweek.

    Only gameweeks strictly before `as_of_gw` are read, which is what makes the
    backtest free of lookahead.
    """
    out: list[dict] = []
    for label, gws in windows_for(as_of_gw).items():
        events = [e for gw in gws for e in events_by_gw.get(gw, [])]
        if not events:
            continue
        for stat in STAT_DEFS:
            out.extend(compute_window(events, stat, as_of_gw, label))
    return out


def _index(rows: list[dict]) -> dict[tuple[int, str, str], dict]:
    return {(r["team_id"], r["stat_type"], r["window_label"]): r for r in rows}


def build_flags(rate_rows: list[dict], season: str, as_of_gw: int) -> list[dict]:
    """Promote rates to trend flags, applying the sample floor and persistence."""
    idx = _index(rate_rows)
    flags: list[dict] = []

    teams = {r["team_id"] for r in rate_rows}
    for team in teams:
        for stat in STAT_DEFS:
            recent = idx.get((team, stat.key, "last4"))
            previous = idx.get((team, stat.key, "prev4"))
            if not recent or recent["shrunk_z"] is None:
                continue
            # Principle 4: below the floor it stays in team_rate_stats only.
            if not recent["meets_sample_floor"]:
                continue

            z_recent = recent["shrunk_z"]
            if abs(z_recent) < Z_CONFIRM:
                continue

            direction = (
                "vulnerable"
                if (z_recent > 0) == stat.higher_is_vulnerable
                else "strong"
            )

            # Principle 5: does the previous, non-overlapping window agree?
            confirmed = False
            z_previous = None
            if previous and previous["shrunk_z"] is not None and previous["meets_sample_floor"]:
                z_previous = previous["shrunk_z"]
                confirmed = (z_previous > 0) == (z_recent > 0) and abs(z_previous) >= Z_CONFIRM

            if confirmed and abs(z_recent) >= Z_STRONG:
                confidence = "high"
            elif confirmed:
                confidence = "medium"
            else:
                confidence = "watch"

            # Principle 7: only medium and high may move a score, and only
            # within the cap. A 'watch' item is information, not an input.
            if confidence == "watch":
                multiplier = 1.0
            else:
                magnitude = min(MAX_MULTIPLIER, MAX_MULTIPLIER * abs(z_recent) / 3.0)
                multiplier = 1.0 + (magnitude if direction == "vulnerable" else -magnitude)

            flags.append(
                {
                    "season": season,
                    "as_of_gw": as_of_gw,
                    "team_id": team,
                    "stat_type": stat.key,
                    "direction": direction,
                    "confidence": confidence,
                    "sample_size": recent["sample_size"],
                    "z_score": z_recent,
                    "shrunk_rate": recent["shrunk_rate"],
                    "league_mean": recent["league_mean"],
                    "first_window_confirmed": True,
                    "second_window_confirmed": bool(confirmed),
                    "points_multiplier": round(multiplier, 4),
                    "label": stat.label,
                    "_z_previous": z_previous,
                }
            )
    return flags


# Stats whose split-half reliability shows them to be genuine, persistent team
# characteristics rather than a property of whoever they happened to play.
# Measured on 2025-26: r = 0.73 and 0.51 respectively, against 0.16 or below
# for every defensive pattern. See README, "Backtest result".
STRUCTURAL_STATS = {"head_xg_share_for", "setpiece_xg_share_for"}


def main(season: str = "2025-26", as_of_gw: int | None = None) -> None:
    """Compute and store rate stats and trend flags for a season.

    Writes both layers: everything into team_rate_stats (including rows below
    the sample floor, per principle 4 -- computed and stored, never promoted),
    and only what clears the floor and the persistence check into trend_flags.
    """
    from common import Run, log, select, upsert

    with Run("trends", season) as run:
        events = select("match_events", f"season=eq.{season}&select=*")
        if not events:
            # Before a ball is kicked there is nothing to compute. That is a
            # normal state, not a failure, and must not fail the pipeline.
            log(f"  no match_events for {season} yet; nothing to compute")
            return

        by_gw: dict[int, list[dict]] = defaultdict(list)
        for e in events:
            if e.get("gw") is not None:
                by_gw[int(e["gw"])].append(e)

        target = as_of_gw or (max(by_gw) + 1)
        log(f"  {len(events)} events, GW{min(by_gw)}-{max(by_gw)}, as of GW{target}")

        rate_rows = build_rate_stats(by_gw, target)
        for r in rate_rows:
            r["season"] = season
        run.rows += upsert(
            "team_rate_stats",
            rate_rows,
            on_conflict="season,as_of_gw,team_id,window_label,stat_type",
        )
        below = sum(1 for r in rate_rows if not r["meets_sample_floor"])
        log(f"  {len(rate_rows)} rate rows ({below} below the sample floor, stored not promoted)")

        flags = build_flags(rate_rows, season, target)
        for f in flags:
            f.pop("_z_previous", None)
        run.rows += upsert(
            "trend_flags", flags, on_conflict="season,as_of_gw,team_id,stat_type"
        )
        tiers: dict[str, int] = defaultdict(int)
        for f in flags:
            tiers[f["confidence"]] += 1
        log(f"  {len(flags)} flags: {dict(tiers)}")


if __name__ == "__main__":
    import sys

    main(sys.argv[1] if len(sys.argv) > 1 else "2025-26")
