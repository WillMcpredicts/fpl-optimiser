"""FPL scoring constants for 2026/27, and the small pieces of maths the model
leans on.

Checked against the live game settings and the 2026/27 rule changes. The BPS
system was overhauled this summer (being tackled is no longer penalised, CBI
now scores per three actions rather than two, keeper saves restructured), which
is why the model carries no BPS over/under-performance term yet -- calibrating
one on 2025/26 data would fit a formula that no longer exists.
"""
from __future__ import annotations

import math

GK, DEF, MID, FWD = 1, 2, 3, 4

GOAL_POINTS = {GK: 6, DEF: 6, MID: 5, FWD: 4}
ASSIST_POINTS = 3
CLEAN_SHEET_POINTS = {GK: 4, DEF: 4, MID: 1, FWD: 0}
APPEARANCE_SHORT = 1          # played, under 60 minutes
APPEARANCE_LONG = 2           # 60 minutes or more
SAVES_PER_POINT = 3           # goalkeepers
CONCEDED_PER_PENALTY = 2      # -1 per 2 conceded, GK and DEF only
DEFCON_POINTS = 2
DEFCON_THRESHOLD = {DEF: 10, MID: 12, FWD: 12}  # GK has no DefCon route

YELLOW_POINTS = -1
RED_POINTS = -3

# League baselines, used as the neutral reference point so that a fixture
# adjustment is measured against an average opponent rather than against zero.
LEAGUE_AVG_GOALS_PER_TEAM = 1.42
HOME_ATTACK_FACTOR = 1.09
AWAY_ATTACK_FACTOR = 0.92

# How strongly an Elo gap moves expected goals. 0.5 over a 400-point gap is a
# deliberately conservative slope; the multiplier is clamped either way so a
# single extreme rating cannot dominate a projection.
ELO_K = 0.5
ELO_REFERENCE = 1750.0
MULTIPLIER_FLOOR, MULTIPLIER_CEILING = 0.55, 1.80


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def elo_multiplier(team_elo: float | None, opponent_elo: float | None) -> float:
    """Attacking multiplier for facing this opponent, 1.0 = league average."""
    if team_elo is None or opponent_elo is None:
        return 1.0
    # Measured against a reference opponent, so a good team facing an average
    # side still reads ~1.0 -- the player's own rate already carries their team.
    diff = ELO_REFERENCE - float(opponent_elo)
    return clamp(math.exp(ELO_K * diff / 400.0), MULTIPLIER_FLOOR, MULTIPLIER_CEILING)


def defensive_elo_multiplier(opponent_elo: float | None) -> float:
    """How much MORE the opponent is expected to score than an average side.

    Higher means a harder fixture for a clean sheet.
    """
    if opponent_elo is None:
        return 1.0
    diff = float(opponent_elo) - ELO_REFERENCE
    return clamp(math.exp(ELO_K * diff / 400.0), MULTIPLIER_FLOOR, MULTIPLIER_CEILING)


def poisson_zero(lam: float) -> float:
    """P(no goals conceded) for a Poisson rate -- the clean sheet probability."""
    return math.exp(-max(0.0, lam))


def poisson_pmf(k: int, lam: float) -> float:
    lam = max(1e-9, lam)
    return math.exp(-lam) * lam ** k / math.factorial(k)


def expected_concede_penalty(lam: float, max_goals: int = 8) -> float:
    """Expected -1-per-2-conceded deduction, summed over the Poisson mass.

    Averaging the rate (-lam/2) would be wrong: the deduction floors at each
    even goal, so 1 conceded costs nothing and 3 costs the same as 2.
    """
    return -sum(
        poisson_pmf(k, lam) * (k // CONCEDED_PER_PENALTY) for k in range(max_goals + 1)
    )
