"""Penalty duty, applied only where it CHANGED.

Measured, not assumed: 92 penalties across 380 Premier League matches in
2025-26 at 82% conversion, so 0.121 per team-match and roughly 0.099 goals to
the designated taker per 90 played.

The important finding is that a blanket penalty bonus does NOT work. Tested
walk-forward on 2025-26, first-choice takers out-scored their own prior rate by
just +0.05 points per appearance, and the best-fitting bonus was zero. The
reason is that a taker's scoring history already contains the penalties they
took -- the model is picking them up through xG, and adding a bonus on top
double-counts.

The gap is duty CHANGE. A player newly appointed to penalties has a history
that does not include them, so the model understates him; a player who has lost
duty is overstated. That is where an adjustment belongs, and only there.
"""
from __future__ import annotations

from scoring import DEF, FWD, GK, GOAL_POINTS, MID

PENALTIES_PER_TEAM_MATCH = 0.121
CONVERSION = 0.82
# Penalty goals also drag bonus points with them; kept modest and separate so
# the figure above stays a clean, checkable measurement.
BONUS_UPLIFT = 0.10


def penalty_points_per_90(position: int) -> float:
    """Points per 90 a first-choice taker gains from penalties alone."""
    goals = PENALTIES_PER_TEAM_MATCH * CONVERSION
    return goals * (GOAL_POINTS.get(position, 4) + BONUS_UPLIFT)


def duty_change(current_order: int | None, prior_order: int | None) -> str:
    """How a player's penalty duty has changed since their history was built."""
    now_first = current_order == 1
    was_first = prior_order == 1
    if now_first and not was_first:
        return "gained"
    if was_first and not now_first:
        return "lost"
    return "unchanged"


def adjustment(position: int, current_order: int | None, prior_order: int | None) -> tuple[float, str]:
    """Points-per-90 correction, and the reason for it.

    Zero when duty is unchanged, because the player's own scoring rate already
    reflects it.
    """
    if position == GK:
        return 0.0, "unchanged"
    change = duty_change(current_order, prior_order)
    if change == "gained":
        return penalty_points_per_90(position), "gained"
    if change == "lost":
        return -penalty_points_per_90(position), "lost"
    return 0.0, "unchanged"
