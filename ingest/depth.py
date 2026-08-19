"""Depth-chart priors for the minutes model.

Historical minutes cannot see a role change. A keeper who sat on the bench all
last season and is now his club's first choice reads as zero minutes; so does a
striker returning from a season-ending injury, and any summer signing. Before a
ball is kicked those players are exactly the ones a projection gets most wrong.

FPL's own pricing is the best available pre-season signal for role, because it
is set by people with squad knowledge and re-set every summer. Within a club and
position, price rank is a good proxy for the pecking order -- a club's most
expensive goalkeeper is almost always the one who plays.

So the minutes model shrinks toward a DEPTH-AWARE prior rather than a flat
positional average. It is still only a prior: once real minutes accumulate, the
weighting in rates.py moves to observed football automatically.
"""
from __future__ import annotations

from collections import defaultdict

from scoring import DEF, FWD, GK, MID

# Expected starter probability by price rank within a club and position.
# Indexed by rank; the final value applies to everyone beyond the list.
DEPTH_P60 = {
    GK:  [0.88, 0.08, 0.03],
    DEF: [0.80, 0.76, 0.72, 0.62, 0.42, 0.20, 0.10],
    MID: [0.76, 0.72, 0.66, 0.56, 0.38, 0.22, 0.12],
    FWD: [0.76, 0.50, 0.28, 0.14],
}
# Chance of at least a cameo, for players not expected to start.
DEPTH_SUB_RATE = {GK: 0.02, DEF: 0.30, MID: 0.42, FWD: 0.45}

MINUTES_IF_START = 82.0
MINUTES_IF_CAMEO = 17.0


def _rank_key(p: dict) -> tuple:
    """Price first, then last season's minutes, then ownership.

    Ownership is the weakest of the three and comes last on purpose: a cheap
    goalkeeper carrying 20% ownership pre-season is usually a bench enabler
    rather than an expected starter, and using it earlier promoted exactly
    those players over established first choices.
    """
    return (
        -(p.get("now_cost") or 0),
        -(p.get("minutes") or 0),
        -float(p.get("selected_by_percent") or 0),
    )


def build_depth_priors(players: list[dict]) -> dict[int, dict]:
    """A minutes prior for every player, keyed by FPL element id."""
    groups: dict[tuple[int, int], list[dict]] = defaultdict(list)
    for p in players:
        groups[(p["team_id"], p["element_type"])].append(p)

    priors: dict[int, dict] = {}
    for (_, position), squad in groups.items():
        ladder = DEPTH_P60.get(position, DEPTH_P60[MID])
        sub_rate = DEPTH_SUB_RATE.get(position, 0.35)
        for rank, p in enumerate(sorted(squad, key=_rank_key)):
            p60 = ladder[rank] if rank < len(ladder) else ladder[-1]
            # A likely starter is also very likely to appear at all; a fringe
            # player's appearance chance is their cameo rate.
            p_any = min(1.0, p60 + (1.0 - p60) * sub_rate)
            priors[p["id"]] = {
                "p60": p60,
                "p_any": p_any,
                "avg_minutes": p60 * MINUTES_IF_START
                + (p_any - p60) * MINUTES_IF_CAMEO,
                "depth_rank": rank,
            }
    return priors
