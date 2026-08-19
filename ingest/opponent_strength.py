"""How generous each team is to each position, in FPL points.

The idea: some sides concede points disproportionately to a position for
structural reasons. Face a dominant possession team and your defenders spend the
match clearing and blocking, so their defensive-contribution points go up
regardless of the scoreline. That is a causal, repeatable effect, unlike the
shot-pattern trends in trends.py which turned out to be mostly fixture-list
noise.

This one earned its place, and the evidence is worth stating precisely because
the margins are small:

  * Within a season, points conceded per 90 is a real team trait for defenders
    (split-half r = 0.52), midfielders (0.47) and keepers (0.35). For forwards
    it is noise (-0.26).

  * Walk-forward over 2025-26, adding it to a player's own scoring rate improved
    predictions by 0.76% on a HELD-OUT second half, with the damping tuned only
    on the first half.

  * Crucially, measured INCREMENTALLY over the Elo fixture adjustment the model
    already applies -- because a strong team both concedes few points and has a
    high Elo, so a naive test double-counts difficulty -- it is worth +0.46%,
    held out. Consistent across keepers, defenders and midfielders (0.54%,
    0.55%, 0.54%) and slightly negative for forwards.

  * Across seasons the signal transfers only partly, and differently by
    position: midfielders carry (r = 0.59), defenders weakly (0.30), forwards
    weakly (0.28), keepers not at all (0.01). So last season's ratings seed the
    new one at position-specific weights, and keepers start from nothing.

Everything here is bounded: the adjustment is damped, then capped, and never
applies to forwards.
"""
from __future__ import annotations

from collections import defaultdict

from scoring import DEF, FWD, GK, MID

# Tuned on GW10-24 of 2025-26 and validated on GW25-38, which it never saw.
DAMPING = 0.4
# Principle 7: a hard ceiling on how far a trend may move a score.
MAX_ADJUSTMENT = 0.15
# Measured cross-season carry-over. Keepers and forwards get nothing: keepers
# because the correlation is 0.01, forwards because the effect is negative.
CROSS_SEASON_WEIGHT = {GK: 0.0, DEF: 0.3, MID: 0.6, FWD: 0.0}
# Positions the adjustment may touch at all.
ELIGIBLE = {GK, DEF, MID}
# Shrinkage toward "league average", in 90s of opponent minutes observed.
SHRINK_90S = 40.0
# Below this, a team-position rate is not used at all.
MIN_90S = 10.0


def build_factors(
    current_rows: list[dict],
    prior_rows: list[dict],
    position_by_player: dict[int, int],
    current_season: str,
) -> dict[tuple[int, int], dict]:
    """Opponent generosity factor per (team_id, position).

    A factor above 1.0 means that team concedes more points than average to that
    position. Returns the factor plus the evidence behind it, so the UI can show
    its working rather than presenting a bare multiplier.
    """
    def accumulate(rows: list[dict]) -> tuple[dict, dict, dict, dict]:
        num: dict[tuple[int, int], float] = defaultdict(float)
        mins: dict[tuple[int, int], float] = defaultdict(float)
        lnum: dict[int, float] = defaultdict(float)
        lmins: dict[int, float] = defaultdict(float)
        for r in rows:
            m = r.get("minutes") or 0
            opp = r.get("opponent_team")
            pos = position_by_player.get(r.get("player_id"))
            if m <= 0 or not opp or not pos:
                continue
            pts = r.get("total_points") or 0
            num[(opp, pos)] += pts
            mins[(opp, pos)] += m
            lnum[pos] += pts
            lmins[pos] += m
        return num, mins, lnum, lmins

    cur_num, cur_min, cur_lnum, cur_lmin = accumulate(current_rows)
    pri_num, pri_min, pri_lnum, pri_lmin = accumulate(prior_rows)

    factors: dict[tuple[int, int], dict] = {}
    keys = set(cur_min) | set(pri_min)
    for team, pos in keys:
        if pos not in ELIGIBLE:
            continue
        cross = CROSS_SEASON_WEIGHT.get(pos, 0.0)

        cur90 = cur_min[(team, pos)] / 90.0
        pri90 = (pri_min[(team, pos)] / 90.0) * cross

        # League rate for this position, preferring the live season once it has
        # enough football to be meaningful.
        cur_league90 = cur_lmin[pos] / 90.0
        if cur_league90 >= MIN_90S * 20:
            league_rate = cur_lnum[pos] / cur_league90
        elif pri_lmin[pos]:
            league_rate = pri_lnum[pos] / (pri_lmin[pos] / 90.0)
        else:
            continue
        if league_rate <= 0:
            continue

        weighted90 = cur90 + pri90
        if weighted90 < MIN_90S:
            continue
        weighted_points = cur_num[(team, pos)] + pri_num[(team, pos)] * cross

        # Empirical-Bayes style shrinkage toward the league rate: a team seen
        # for only a few matches should read close to average.
        shrunk = (weighted_points + league_rate * SHRINK_90S) / (weighted90 + SHRINK_90S)
        raw_factor = shrunk / league_rate
        damped = 1.0 + DAMPING * (raw_factor - 1.0)
        capped = max(1.0 - MAX_ADJUSTMENT, min(1.0 + MAX_ADJUSTMENT, damped))

        factors[(team, pos)] = {
            "factor": round(capped, 4),
            "raw_ratio": round(raw_factor, 4),
            "rate": round(shrunk, 4),
            "league_rate": round(league_rate, 4),
            "current_90s": round(cur90, 1),
            "prior_90s_weighted": round(pri90, 1),
            "was_capped": abs(damped - capped) > 1e-9,
        }
    return factors


def factor_for(
    factors: dict[tuple[int, int], dict], opponent_id: int, position: int
) -> tuple[float, dict | None]:
    if position not in ELIGIBLE:
        return 1.0, None
    entry = factors.get((opponent_id, position))
    if not entry:
        return 1.0, None
    return entry["factor"], entry
