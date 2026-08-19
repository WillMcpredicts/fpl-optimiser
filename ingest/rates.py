"""Per-player rate estimation.

Every rate is shrunk toward a positional league mean in proportion to how much
football it is based on -- the same empirical-Bayes idea principle 3 applies to
teams, applied at player level. A striker with 40 minutes of evidence should
not read as the best xG90 in the league.

Last season is blended in at a discount rather than used raw. Pre-season it is
all we have; by October the live data outweighs it naturally, because the
weights are in units of 90s played.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Iterable

from depth import build_depth_priors
from scoring import DEF, DEFCON_THRESHOLD, FWD, GK, MID

# Shrinkage strength, in 90s. A player with SHRINK_90S of football sits halfway
# between their own rate and the positional mean.
SHRINK_90S = 6.0
# Last season counts, but less than this season.
PRIOR_DISCOUNT = 0.55
# Minutes-model shrinkage is gentler: availability patterns stabilise fast.
MINUTES_SHRINK_GAMES = 4.0

RATE_FIELDS = ("xg90", "xa90", "bonus90", "saves90", "yellow90")


def _safe_div(n: float, d: float) -> float:
    return n / d if d else 0.0


def positional_priors(rows_by_position: dict[int, list[dict]]) -> dict[int, dict]:
    """League-average per-90 rates per position, the target of the shrinkage."""
    priors: dict[int, dict] = {}
    for pos, rows in rows_by_position.items():
        mins = sum(r["minutes"] for r in rows)
        n90 = _safe_div(mins, 90.0)
        played = [r for r in rows if r["minutes"] > 0]
        starts60 = [r for r in rows if r["minutes"] >= 60]
        priors[pos] = {
            "xg90": _safe_div(sum(r["xg"] for r in rows), n90),
            "xa90": _safe_div(sum(r["xa"] for r in rows), n90),
            "bonus90": _safe_div(sum(r["bonus"] for r in rows), n90),
            "saves90": _safe_div(sum(r["saves"] for r in rows), n90),
            "yellow90": _safe_div(sum(r["yellows"] for r in rows), n90),
            "p60": _safe_div(len(starts60), len(rows)),
            "p_any": _safe_div(len(played), len(rows)),
            "avg_minutes": _safe_div(mins, len(rows)),
            "defcon_rate": _safe_div(
                sum(1 for r in starts60 if r["defcon"] >= DEFCON_THRESHOLD.get(pos, 99)),
                len(starts60),
            ),
        }
    return priors


def normalise_gw_rows(rows: Iterable[dict]) -> list[dict]:
    """Reduce a player_gameweeks row to just what the rate maths needs."""
    out = []
    for r in rows:
        out.append(
            {
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


def _blend(
    current: list[dict],
    prior: list[dict],
    prior_mean: dict,
    position: int,
    minutes_prior: dict,
) -> dict:
    """Weighted blend of this season, last season and the positional mean."""
    cur_90s = _safe_div(sum(r["minutes"] for r in current), 90.0)
    pri_90s = _safe_div(sum(r["minutes"] for r in prior), 90.0) * PRIOR_DISCOUNT

    def rate(field: str, key: str) -> float:
        cur_total = sum(r[key] for r in current)
        pri_total = sum(r[key] for r in prior) * PRIOR_DISCOUNT
        weight = cur_90s + pri_90s + SHRINK_90S
        return _safe_div(
            cur_total + pri_total + prior_mean[field] * SHRINK_90S, weight
        )

    blended = {
        "xg90": rate("xg90", "xg"),
        "xa90": rate("xa90", "xa"),
        "bonus90": rate("bonus90", "bonus"),
        "saves90": rate("saves90", "saves"),
        "yellow90": rate("yellow90", "yellows"),
    }

    # Minutes side: counts of appearances rather than per-90 totals.
    cur_games = len(current)
    pri_games = len(prior) * PRIOR_DISCOUNT
    denom = cur_games + pri_games + MINUTES_SHRINK_GAMES

    def game_rate(field: str, predicate) -> float:
        cur_n = sum(1 for r in current if predicate(r))
        pri_n = sum(1 for r in prior if predicate(r)) * PRIOR_DISCOUNT
        return _safe_div(
            cur_n + pri_n + minutes_prior[field] * MINUTES_SHRINK_GAMES, denom
        )

    blended["p60"] = game_rate("p60", lambda r: r["minutes"] >= 60)
    blended["p_any"] = game_rate("p_any", lambda r: r["minutes"] > 0)
    blended["avg_minutes"] = _safe_div(
        sum(r["minutes"] for r in current)
        + sum(r["minutes"] for r in prior) * PRIOR_DISCOUNT
        + minutes_prior["avg_minutes"] * MINUTES_SHRINK_GAMES,
        denom,
    )

    threshold = DEFCON_THRESHOLD.get(position, 99)
    cur_60 = [r for r in current if r["minutes"] >= 60]
    pri_60 = [r for r in prior if r["minutes"] >= 60]
    d_denom = len(cur_60) + len(pri_60) * PRIOR_DISCOUNT + MINUTES_SHRINK_GAMES
    blended["defcon_rate"] = _safe_div(
        sum(1 for r in cur_60 if r["defcon"] >= threshold)
        + sum(1 for r in pri_60 if r["defcon"] >= threshold) * PRIOR_DISCOUNT
        + prior_mean["defcon_rate"] * MINUTES_SHRINK_GAMES,
        d_denom,
    )

    blended["depth_rank"] = minutes_prior["depth_rank"]
    blended["depth_prior_p60"] = round(minutes_prior["p60"], 3)
    blended["evidence_90s"] = round(cur_90s + pri_90s, 2)
    blended["current_90s"] = round(cur_90s, 2)
    blended["games_observed"] = len(current) + len(prior)
    return blended


# How far a team's strength is allowed to move the prior for a player with no
# history of their own. Without this, every promoted-club signing inherits a
# league-average xG90 and reads like a mid-table regular.
TEAM_PRIOR_FLOOR, TEAM_PRIOR_CEILING = 0.65, 1.35


def team_prior_scale(team_elo: float | None, league_mean_elo: float) -> float:
    """Attacking-prior multiplier from team strength, 1.0 at the league mean."""
    if not team_elo or not league_mean_elo:
        return 1.0
    scale = 1.0 + (float(team_elo) - league_mean_elo) / 400.0
    return max(TEAM_PRIOR_FLOOR, min(TEAM_PRIOR_CEILING, scale))


def build_player_rates(
    players: list[dict],
    current_by_code: dict[int, list[dict]],
    prior_by_code: dict[int, list[dict]],
    team_elo: dict[int, float] | None = None,
) -> dict[int, dict]:
    """Rates for every player, keyed by FPL element id for the current season."""
    by_position: dict[int, list[dict]] = defaultdict(list)
    for p in players:
        rows = normalise_gw_rows(
            current_by_code.get(p["code"], []) + prior_by_code.get(p["code"], [])
        )
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
        # Only the attacking rates scale with team strength; appearance and
        # discipline rates are properties of the player, not the club.
        prior_mean = dict(base_prior)
        for field in ("xg90", "xa90", "bonus90"):
            prior_mean[field] = base_prior.get(field, 0.0) * scale
        current = normalise_gw_rows(current_by_code.get(p["code"], []))
        prior = normalise_gw_rows(prior_by_code.get(p["code"], []))
        rates = _blend(current, prior, prior_mean, pos, depth[p["id"]])
        rates["position"] = pos
        rates["team_prior_scale"] = round(scale, 3)
        out[p["id"]] = rates
    return out
