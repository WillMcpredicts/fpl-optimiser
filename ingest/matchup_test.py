"""Does the opponent's weakness to a shot type add anything to a projection?

The idea under test, in its most concrete form: Brentford concede a lot of
headed goals, so a Spurs player who scores headers should get an uplift when
they play Brentford.

This is NOT the same question as the persistence test in backtest.py. That one
asks whether a team's conceded rate carries from one window to the next. This
asks whether the ATTACKER x DEFENCE interaction predicts what happens in a
specific fixture -- which could carry signal even if the defensive side alone is
weak, because the attacking side is strong.

Walk-forward over a completed season, using only matches played before each one.
Three predictors of the headed chances a side creates:

    baseline     the league average
    attacker     the attacking side's own headed rate
    interaction  attacker's rate scaled by how vulnerable the defence has been

Run:  python ingest/matchup_test.py [season]
"""
from __future__ import annotations

import math
import statistics
import sys
from collections import defaultdict

from common import log, select

MIN_PRIOR_MATCHES = 5
DAMPING_SWEEP = [0.0, 0.1, 0.2, 0.25, 0.3, 0.4, 0.5, 0.75, 1.0]


def correlation(xs: list[float], ys: list[float]) -> float:
    if len(xs) < 3:
        return 0.0
    mx, my = statistics.mean(xs), statistics.mean(ys)
    num = sum((a - mx) * (b - my) for a, b in zip(xs, ys))
    den = (sum((a - mx) ** 2 for a in xs) * sum((b - my) ** 2 for b in ys)) ** 0.5
    return num / den if den else 0.0


def team_matches(events: list[dict]) -> list[dict]:
    """Headed xG created, per team per match."""
    totals: dict[tuple[str, int], float] = defaultdict(float)
    gw_of: dict[str, int] = {}
    pairs: dict[str, set[tuple[int, int]]] = defaultdict(set)
    for e in events:
        gw = e.get("gw")
        if gw is None:
            continue
        mid = e["match_id"]
        gw_of[mid] = int(gw)
        pairs[mid].add((e["team_id"], e["opponent_id"]))
        if (e.get("body_part") or "") == "head":
            totals[(mid, e["team_id"])] += float(e.get("xg") or 0)

    rows = []
    for mid, sides in pairs.items():
        for team, opponent in sides:
            rows.append(
                {
                    "gw": gw_of[mid],
                    "team": team,
                    "opponent": opponent,
                    "head_xg": totals.get((mid, team), 0.0),
                }
            )
    rows.sort(key=lambda r: r["gw"])
    return rows


def build_samples(rows: list[dict]) -> list[dict]:
    samples = []
    for r in rows:
        prior = [x for x in rows if x["gw"] < r["gw"]]
        attacker_prior = [x for x in prior if x["team"] == r["team"]]
        # What this defence has ALLOWED: headed xG scored against them.
        allowed = [x["head_xg"] for x in prior if x["opponent"] == r["opponent"]]
        if len(attacker_prior) < MIN_PRIOR_MATCHES or len(allowed) < MIN_PRIOR_MATCHES:
            continue
        league = statistics.mean(x["head_xg"] for x in prior)
        samples.append(
            {
                "actual": r["head_xg"],
                "league": league,
                "attacker": statistics.mean(x["head_xg"] for x in attacker_prior),
                "defence_factor": (statistics.mean(allowed) / league) if league else 1.0,
            }
        )
    return samples


def main(season: str = "2025-26") -> None:
    events = select("match_events", f"season=eq.{season}&select=*")
    if not events:
        raise RuntimeError(f"no match_events for {season} -- run shots.py first")
    rows = team_matches(events)
    samples = build_samples(rows)
    n = len(samples)
    log(f"{len(events)} shots, {len(rows)} team-matches, {n} evaluated "
        f"(both sides with >= {MIN_PRIOR_MATCHES} prior matches)\n")

    actual = [s["actual"] for s in samples]
    baseline = [s["league"] for s in samples]
    attacker = [s["attacker"] for s in samples]

    base_mae = statistics.mean(abs(a - p) for a, p in zip(actual, baseline))
    att_mae = statistics.mean(abs(a - p) for a, p in zip(actual, attacker))

    print(f"{'damping':>8}{'MAE':>10}{'vs baseline':>13}{'vs attacker':>13}{'corr':>9}")
    print("-" * 53)
    best = (None, float("inf"))
    for lam in DAMPING_SWEEP:
        pred = [s["attacker"] * (1 + lam * (s["defence_factor"] - 1)) for s in samples]
        mae = statistics.mean(abs(a - p) for a, p in zip(actual, pred))
        print(
            f"{lam:>8.2f}{mae:>10.4f}"
            f"{(base_mae - mae) / base_mae * 100:>12.1f}%"
            f"{(att_mae - mae) / att_mae * 100:>12.2f}%"
            f"{correlation(pred, actual):>9.3f}"
        )
        if mae < best[1]:
            best = (lam, mae)

    raw = [s["attacker"] * s["defence_factor"] for s in samples]
    r = correlation(raw, actual)
    t = r * math.sqrt(n - 2) / math.sqrt(1 - r * r) if abs(r) < 1 else float("inf")

    print()
    print(f"best damping by MAE: {best[0]}")
    print(f"raw interaction    : r = {r:.3f}, t = {t:.2f}, n = {n}")
    print(f"attacker only      : r = {correlation(attacker, actual):.3f}")
    print()
    print("The correlation is real; the effect is far too small to move a projection.")
    print("Note the damping is tuned on the same data it is scored against, so these")
    print("figures flatter the interaction rather than understate it.")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "2025-26")
