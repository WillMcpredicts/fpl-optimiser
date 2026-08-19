"""Per-player rate estimation.

Every rate is shrunk toward a prior in proportion to how much football it is
based on -- the same empirical-Bayes idea principle 3 applies to teams, applied
at player level. A striker with 40 minutes of evidence should not read as the
best xG90 in the league.

Three seasons of history are used, each weighted by age (see config.SEASON_DECAY)
so last season counts for more than three seasons ago. Weights are carried on
each row rather than applied to aggregates, which keeps the maths readable when
seasons contribute different columns.

That last point matters: Defensive Contribution did not exist before 2025/26 and
the columns are simply absent from earlier data. Those rows are excluded from
DefCon rates rather than counted as zero -- counting them would quietly halve
every defender's DefCon rate and make the whole position look worse than it is.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Iterable

from config import SEASONS_WITHOUT_DEFCON, season_weight
from depth import build_depth_priors
from scoring import DEF, DEFCON_THRESHOLD, FWD, GK, MID

# Shrinkage strength, in weighted 90s. A player with this much football sits
# halfway between their own rate and the prior.
SHRINK_90S = 6.0
# Minutes-model shrinkage is gentler: availability patterns stabilise fast.
MINUTES_SHRINK_GAMES = 4.0

# Appearance probabilities come out systematically high, and it matters: a
# backtest over 2025-26 predicted 25.2 minutes a player against 21.8 actual,
# with the excess concentrated in the 0.2-0.5 band -- squad players who look
# like they might feature and mostly do not.
#
# The ORDERING was already good (each predicted band appeared more often than
# the one below it), so this is a calibration curve rather than a rethink.
# Raising the probability to a power above 1 leaves confident cases alone and
# pulls the uncertain middle down, which is where the error was.
APPEARANCE_CALIBRATION = 1.35


def calibrate(p: float) -> float:
    """Bend an appearance probability onto the observed frequency curve."""
    if p <= 0.0:
        return 0.0
    if p >= 1.0:
        return 1.0
    return p ** APPEARANCE_CALIBRATION

# How far team strength may move the prior for a player with no history of their
# own. Without it, every promoted-club signing inherits a league-average xG90.
TEAM_PRIOR_FLOOR, TEAM_PRIOR_CEILING = 0.65, 1.35


def _safe_div(n: float, d: float) -> float:
    return n / d if d else 0.0


def team_prior_scale(team_elo: float | None, league_mean_elo: float) -> float:
    """Attacking-prior multiplier from team strength, 1.0 at the league mean."""
    if not team_elo or not league_mean_elo:
        return 1.0
    scale = 1.0 + (float(team_elo) - league_mean_elo) / 400.0
    return max(TEAM_PRIOR_FLOOR, min(TEAM_PRIOR_CEILING, scale))


def normalise_gw_rows(rows: Iterable[dict]) -> list[dict]:
    """Reduce player_gameweeks rows to what the rate maths needs, with weights."""
    out = []
    for r in rows:
        season = r.get("season") or ""
        out.append(
            {
                "w": season_weight(season) if season else 1.0,
                "defcon_known": season not in SEASONS_WITHOUT_DEFCON,
                "minutes": r.get("minutes") or 0,
                "starts": r.get("starts") or 0,
                "xg": float(r.get("expected_goals") or 0),
                "xa": float(r.get("expected_assists") or 0),
                "bonus": r.get("bonus") or 0,
                "saves": r.get("saves") or 0,
                "yellows": r.get("yellow_cards") or 0,
                "defcon": r.get("defensive_contribution") or 0,
            }
        )
    return out


def positional_priors(rows_by_position: dict[int, list[dict]]) -> dict[int, dict]:
    """League-average per-90 rates per position, the target of the shrinkage."""
    priors: dict[int, dict] = {}
    for pos, rows in rows_by_position.items():
        w90 = _safe_div(sum(r["w"] * r["minutes"] for r in rows), 90.0)
        wgames = sum(r["w"] for r in rows)
        played = [r for r in rows if r["minutes"] > 0]
        starts60 = [r for r in rows if r["minutes"] >= 60]
        # DefCon only from seasons that actually recorded it.
        defcon_rows = [r for r in starts60 if r["defcon_known"]]
        defcon_w = sum(r["w"] for r in defcon_rows)
        threshold = DEFCON_THRESHOLD.get(pos, 99)
        priors[pos] = {
            "xg90": _safe_div(sum(r["w"] * r["xg"] for r in rows), w90),
            "xa90": _safe_div(sum(r["w"] * r["xa"] for r in rows), w90),
            "bonus90": _safe_div(sum(r["w"] * r["bonus"] for r in rows), w90),
            "saves90": _safe_div(sum(r["w"] * r["saves"] for r in rows), w90),
            "yellow90": _safe_div(sum(r["w"] * r["yellows"] for r in rows), w90),
            "p60": _safe_div(sum(r["w"] for r in starts60), wgames),
            "p_any": _safe_div(sum(r["w"] for r in played), wgames),
            "avg_minutes": _safe_div(sum(r["w"] * r["minutes"] for r in rows), wgames),
            "defcon_rate": _safe_div(
                sum(r["w"] for r in defcon_rows if r["defcon"] >= threshold), defcon_w
            ),
        }
    return priors


def _blend(rows: list[dict], prior_mean: dict, position: int, minutes_prior: dict) -> dict:
    """Weighted blend of a player's own history and the prior."""
    w90 = _safe_div(sum(r["w"] * r["minutes"] for r in rows), 90.0)
    wgames = sum(r["w"] for r in rows)

    def rate(field: str, key: str) -> float:
        total = sum(r["w"] * r[key] for r in rows)
        return _safe_div(total + prior_mean[field] * SHRINK_90S, w90 + SHRINK_90S)

    blended = {
        "xg90": rate("xg90", "xg"),
        "xa90": rate("xa90", "xa"),
        "bonus90": rate("bonus90", "bonus"),
        "saves90": rate("saves90", "saves"),
        "yellow90": rate("yellow90", "yellows"),
    }

    # Minutes side: weighted appearance counts, shrunk toward the depth prior.
    denom = wgames + MINUTES_SHRINK_GAMES

    def game_rate(field: str, predicate) -> float:
        hit = sum(r["w"] for r in rows if predicate(r))
        return _safe_div(hit + minutes_prior[field] * MINUTES_SHRINK_GAMES, denom)

    raw_p60 = game_rate("p60", lambda r: r["minutes"] >= 60)
    raw_p_any = game_rate("p_any", lambda r: r["minutes"] > 0)
    blended["p60"] = calibrate(raw_p60)
    blended["p_any"] = calibrate(raw_p_any)
    blended["raw_p_any"] = round(raw_p_any, 4)
    raw_minutes = _safe_div(
        sum(r["w"] * r["minutes"] for r in rows)
        + minutes_prior["avg_minutes"] * MINUTES_SHRINK_GAMES,
        denom,
    )
    # Minutes follow the same correction, so expected points scale with it.
    blended["avg_minutes"] = raw_minutes * (
        calibrate(raw_p_any) / raw_p_any if raw_p_any > 0 else 1.0
    )

    # DefCon: only rows from seasons that recorded it.
    threshold = DEFCON_THRESHOLD.get(position, 99)
    defcon_rows = [r for r in rows if r["minutes"] >= 60 and r["defcon_known"]]
    defcon_w = sum(r["w"] for r in defcon_rows)
    blended["defcon_rate"] = _safe_div(
        sum(r["w"] for r in defcon_rows if r["defcon"] >= threshold)
        + prior_mean["defcon_rate"] * MINUTES_SHRINK_GAMES,
        defcon_w + MINUTES_SHRINK_GAMES,
    )

    blended["evidence_90s"] = round(w90, 2)
    blended["current_90s"] = round(
        _safe_div(sum(r["minutes"] for r in rows if r["w"] == 1.0), 90.0), 2
    )
    blended["defcon_evidence_games"] = round(defcon_w, 1)
    blended["games_observed"] = len(rows)
    blended["depth_rank"] = minutes_prior["depth_rank"]
    blended["depth_prior_p60"] = round(minutes_prior["p60"], 3)
    return blended


def build_player_rates(
    players: list[dict],
    rows_by_code: dict[int, list[dict]],
    team_elo: dict[int, float] | None = None,
) -> dict[int, dict]:
    """Rates for every player, keyed by FPL element id for the current season.

    `rows_by_code` holds every player_gameweeks row for that player across all
    ingested seasons, each carrying its own `season` so recency weighting and
    the DefCon availability check can be applied per row.
    """
    by_position: dict[int, list[dict]] = defaultdict(list)
    normalised: dict[int, list[dict]] = {}
    for p in players:
        rows = normalise_gw_rows(rows_by_code.get(p["code"], []))
        normalised[p["id"]] = rows
        by_position[p["element_type"]].extend(rows)
    priors = positional_priors(by_position)
    depth = build_depth_priors(players)

    team_elo = team_elo or {}
    elos = [v for v in team_elo.values() if v]
    league_mean_elo = sum(elos) / len(elos) if elos else 0.0

    out: dict[int, dict] = {}
    for p in players:
        pos = p["element_type"]
        base_prior = priors.get(pos) or priors.get(MID, {})
        scale = team_prior_scale(team_elo.get(p["team_id"]), league_mean_elo)
        # Only attacking rates scale with team strength; appearance and
        # discipline rates are properties of the player, not the club.
        prior_mean = dict(base_prior)
        for field in ("xg90", "xa90", "bonus90"):
            prior_mean[field] = base_prior.get(field, 0.0) * scale

        rates = _blend(normalised[p["id"]], prior_mean, pos, depth[p["id"]])
        rates["position"] = pos
        rates["team_prior_scale"] = round(scale, 3)
        out[p["id"]] = rates
    return out
