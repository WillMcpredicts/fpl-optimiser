"""Principle 6: prove the trend engine predicts forward performance, or don't use it.

The test walks a completed season gameweek by gameweek. At each point it builds
trend flags from ONLY the gameweeks already played, then scores those flags
against what actually happened over the following gameweeks. Two predictors of
that forward rate are compared:

    baseline  -- the league mean. "Assume this team is average."
    trend     -- the team's shrunk rate. "Assume the pattern continues."

If the trend engine cannot beat "assume average", it is pattern-matching noise
and has no business adjusting anyone's predicted points.

Reported per stat and per confidence tier, because the answer is not the same
for all of them -- and the point of the exercise is to find which ones earn
their place, not to produce a single flattering number.
"""
from __future__ import annotations

import json
import pathlib
import statistics
import sys
from collections import defaultdict

from common import Run, delete_where, log, select, upsert
from trends import (
    MIN_EVENTS,
    STAT_DEFS,
    WINDOW,
    aggregate,
    build_flags,
    build_rate_stats,
)

# Matches ahead to score against -- the planner's own 3-gameweek horizon.
FORWARD = 3
# Need two full windows behind before a persistence check means anything.
FIRST_TESTABLE_GW = 2 * WINDOW + 1


def group_by_gw(events: list[dict]) -> dict[int, list[dict]]:
    out: dict[int, list[dict]] = defaultdict(list)
    for e in events:
        gw = e.get("gw")
        if gw is not None:
            out[int(gw)].append(e)
    return out


def forward_rates(events_by_gw: dict[int, list[dict]], stat, gws) -> dict[int, float]:
    """Each team's ACTUAL rate over the forward window, where the sample allows."""
    events = [e for gw in gws for e in events_by_gw.get(gw, [])]
    pairs = aggregate(events, stat)
    return {
        team: n / d
        for team, (n, d) in pairs.items()
        if d >= MIN_EVENTS  # do not score against a handful of shots
    }


def run(events_by_gw: dict[int, list[dict]], season: str) -> list[dict]:
    """Walk the season and collect one record per flag, with its forward outcome."""
    played = sorted(events_by_gw)
    last_gw = max(played) if played else 0
    records: list[dict] = []

    for as_of in range(FIRST_TESTABLE_GW, last_gw - FORWARD + 2):
        # Only gameweeks strictly before `as_of` -- no lookahead.
        history = {gw: ev for gw, ev in events_by_gw.items() if gw < as_of}
        rate_rows = build_rate_stats(history, as_of)
        if not rate_rows:
            continue
        flags = build_flags(rate_rows, season, as_of)
        if not flags:
            continue

        forward_gws = range(as_of, min(as_of + FORWARD, last_gw + 1))
        actual_by_stat = {
            s.key: forward_rates(events_by_gw, s, forward_gws) for s in STAT_DEFS
        }

        for f in flags:
            actual = actual_by_stat.get(f["stat_type"], {}).get(f["team_id"])
            if actual is None:
                continue
            mean = f["league_mean"]
            records.append(
                {
                    "as_of_gw": as_of,
                    "team_id": f["team_id"],
                    "stat_type": f["stat_type"],
                    "confidence": f["confidence"],
                    "direction": f["direction"],
                    "sample_size": f["sample_size"],
                    "z_score": f["z_score"],
                    "actual": actual,
                    "baseline_error": abs(actual - mean),
                    "trend_error": abs(actual - f["shrunk_rate"]),
                    # Did the flag call the right side of the league average?
                    "hit": (actual > mean) == (f["z_score"] > 0),
                }
            )
    return records


def summarise(records: list[dict], season: str) -> list[dict]:
    """Aggregate to one row per stat per confidence tier."""
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in records:
        groups[(r["stat_type"], r["confidence"])].append(r)

    rows = []
    for (stat_type, confidence), items in sorted(groups.items()):
        baseline = statistics.mean(i["baseline_error"] for i in items)
        trend = statistics.mean(i["trend_error"] for i in items)
        hit = statistics.mean(1.0 if i["hit"] else 0.0 for i in items)
        improvement = ((baseline - trend) / baseline * 100) if baseline else 0.0
        # A flag earns its place only if it beats "assume average" on error AND
        # calls the correct side of the mean more often than a coin toss.
        passed = improvement > 0 and hit > 0.5 and len(items) >= 20
        rows.append(
            {
                "season": season,
                "stat_type": stat_type,
                "confidence": confidence,
                "flags_evaluated": len(items),
                "baseline_mae": round(baseline, 6),
                "trend_mae": round(trend, 6),
                "improvement_pct": round(improvement, 2),
                "hit_rate": round(hit, 4),
                "baseline_hit_rate": 0.5,
                "passed": passed,
                "notes": (
                    f"walk-forward, {FORWARD}-gameweek horizon, "
                    f"{WINDOW}-match windows, min {MIN_EVENTS} events"
                ),
            }
        )
    return rows


def report(rows: list[dict]) -> None:
    order = {"high": 0, "medium": 1, "watch": 2}
    rows = sorted(rows, key=lambda r: (order.get(r["confidence"], 9), -r["flags_evaluated"]))

    print(f"\n{'stat':<46}{'conf':<8}{'n':>5}{'base MAE':>10}{'trend MAE':>11}{'improv':>9}{'hit':>8}  verdict")
    print("-" * 111)
    for r in rows:
        print(
            f"{r['stat_type'][:45]:<46}{r['confidence']:<8}{r['flags_evaluated']:>5}"
            f"{r['baseline_mae']:>10.4f}{r['trend_mae']:>11.4f}"
            f"{r['improvement_pct']:>8.1f}%{r['hit_rate']:>8.2f}  "
            f"{'PASS' if r['passed'] else 'fail'}"
        )

    for tier in ("high", "medium", "watch"):
        tier_rows = [r for r in rows if r["confidence"] == tier]
        if not tier_rows:
            continue
        n = sum(r["flags_evaluated"] for r in tier_rows)
        passed = [r for r in tier_rows if r["passed"]]
        weighted = sum(r["improvement_pct"] * r["flags_evaluated"] for r in tier_rows) / n
        hit = sum(r["hit_rate"] * r["flags_evaluated"] for r in tier_rows) / n
        print(
            f"\n{tier:>6}: {len(passed)}/{len(tier_rows)} stats pass · "
            f"{n} flags · weighted improvement {weighted:+.1f}% · hit rate {hit:.2f}"
        )


def load_cached(path: str) -> list[dict]:
    return json.loads(pathlib.Path(path).read_text())["match_events"]


def main() -> None:
    season = sys.argv[1] if len(sys.argv) > 1 else "2025-26"
    cache = None
    for i, a in enumerate(sys.argv):
        if a == "--cache" and i + 1 < len(sys.argv):
            cache = sys.argv[i + 1]

    if cache:
        events = load_cached(cache)
        log(f"loaded {len(events)} shot events from cache")
    else:
        events = select("match_events", f"season=eq.{season}&select=*")
        log(f"loaded {len(events)} shot events from Supabase")

    by_gw = group_by_gw(events)
    log(f"{len(by_gw)} gameweeks, GW{min(by_gw)}-{max(by_gw)}")

    records = run(by_gw, season)
    log(f"{len(records)} flag-outcomes evaluated")
    rows = summarise(records, season)
    report(rows)

    if not cache:
        with Run("backtest", season) as r:
            # Replace, do not merge. An upsert keyed on (season, stat, tier)
            # updates the rows a run produces but leaves behind any combination
            # an earlier run produced and this one did not -- so the table ends
            # up showing two different runs at once, which is worse than showing
            # nothing. A backtest result is only meaningful as a whole.
            delete_where("backtest_results", f"season=eq.{season}")
            r.rows = upsert(
                "backtest_results", rows, on_conflict="season,stat_type,confidence"
            )


if __name__ == "__main__":
    main()
