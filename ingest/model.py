"""Phase 1 predicted points.

A weighted formula, not a learned model: 38 gameweeks a season is not enough
data for ML to generalise, and a formula can show its working.

The decomposition is deliberate and load-bearing:

    final_score = base_score + fixture_adjustment + trend_adjustment

`base_score` is the player scored against a league-average opponent at a
neutral venue. `fixture_adjustment` is the delta from swapping in their actual
opponent, venue and Elo gap. `trend_adjustment` is zero until the trend engine
has passed its backtest and been switched on, so a Phase 1 number is always
base + fixture and the UI can prove it.
"""
from __future__ import annotations

import json
from collections import defaultdict

from common import Run, log, select, upsert
from config import CURRENT_SEASON, VAASTAV_SEASONS
import opponent_strength
from rates import build_player_rates
from scoring import (
    APPEARANCE_LONG,
    APPEARANCE_SHORT,
    ASSIST_POINTS,
    AWAY_ATTACK_FACTOR,
    CLEAN_SHEET_POINTS,
    DEF,
    DEFCON_POINTS,
    ELO_K,
    ELO_REFERENCE,
    FWD,
    GK,
    GOAL_POINTS,
    HOME_ATTACK_FACTOR,
    LEAGUE_AVG_GOALS_PER_TEAM,
    MID,
    SAVES_PER_POINT,
    YELLOW_POINTS,
    clamp,
    elo_multiplier,
    expected_concede_penalty,
    poisson_zero,
)

MODEL_VERSION = "phase1-2026-08"
HORIZON = 3  # gameweeks projected ahead

# How a player's FPL status maps to the chance they are available at all.
STATUS_AVAILABILITY = {
    "a": 1.0,   # available
    "d": 0.5,   # doubtful, overridden by chance_of_playing when FPL gives one
    "i": 0.0,   # injured
    "s": 0.0,   # suspended
    "u": 0.0,   # unavailable
    "n": 0.0,   # not in squad
}


def availability(player: dict) -> tuple[float, str]:
    """Probability the player is available, and why."""
    status = (player.get("status") or "a").lower()
    chance = player.get("chance_of_playing_next_round")
    if chance is not None:
        return clamp(float(chance) / 100.0, 0.0, 1.0), f"FPL chance_of_playing {chance}%"
    base = STATUS_AVAILABILITY.get(status, 1.0)
    return base, f"status '{status}'"


def team_concede_lambda(team_elo, opponent_elo, is_home: bool) -> float:
    """Expected goals conceded by this team in this fixture."""
    import math

    if team_elo is None or opponent_elo is None:
        opp_attack = team_defence = 1.0
    else:
        opp_attack = clamp(
            math.exp(ELO_K * (float(opponent_elo) - ELO_REFERENCE) / 400.0), 0.55, 1.8
        )
        team_defence = clamp(
            math.exp(ELO_K * (ELO_REFERENCE - float(team_elo)) / 400.0), 0.55, 1.8
        )
    venue = AWAY_ATTACK_FACTOR if is_home else HOME_ATTACK_FACTOR
    return LEAGUE_AVG_GOALS_PER_TEAM * opp_attack * team_defence * venue


def score_fixture(rates: dict, avail: float, attack_mult: float, concede_lam: float) -> dict:
    """Expected points for one player in one fixture, broken into its parts."""
    pos = rates["position"]
    p60 = clamp(rates["p60"] * avail, 0.0, 1.0)
    p_any = clamp(rates["p_any"] * avail, 0.0, 1.0)
    minutes = rates["avg_minutes"] * avail
    n90 = minutes / 90.0

    appearance = p_any * APPEARANCE_SHORT + p60 * (APPEARANCE_LONG - APPEARANCE_SHORT)
    goals = rates["xg90"] * n90 * attack_mult * GOAL_POINTS[pos]
    assists = rates["xa90"] * n90 * attack_mult * ASSIST_POINTS

    clean_sheet = 0.0
    conceded = 0.0
    if CLEAN_SHEET_POINTS[pos]:
        clean_sheet = p60 * poisson_zero(concede_lam) * CLEAN_SHEET_POINTS[pos]
    if pos in (GK, DEF):
        conceded = p60 * expected_concede_penalty(concede_lam)

    saves = 0.0
    if pos == GK:
        # More saves against a side expected to shoot more.
        saves = rates["saves90"] * n90 * (concede_lam / LEAGUE_AVG_GOALS_PER_TEAM) / SAVES_PER_POINT

    defcon = 0.0
    if pos in (DEF, MID, FWD):
        defcon = p60 * rates["defcon_rate"] * DEFCON_POINTS

    bonus = rates["bonus90"] * n90
    cards = rates["yellow90"] * n90 * YELLOW_POINTS

    total = appearance + goals + assists + clean_sheet + conceded + saves + defcon + bonus + cards
    return {
        "total": total,
        "appearance": appearance,
        "goals": goals,
        "assists": assists,
        "clean_sheet": clean_sheet,
        "conceded": conceded,
        "saves": saves,
        "defcon": defcon,
        "bonus": bonus,
        "cards": cards,
        "expected_minutes": minutes,
        "p60": p60,
        "p_any": p_any,
    }


def confidence_tier(rates: dict) -> str:
    """How much football the estimate rests on. Shown, never hidden."""
    n = rates["evidence_90s"]
    if n >= 15:
        return "high"
    if n >= 6:
        return "medium"
    return "low"


def load_gate() -> dict:
    """Whether trend adjustments are allowed to move a score, and by how much."""
    rows = select("trend_engine_gate", "select=*")
    if not rows:
        return {"enabled": False, "max_adjustment": 0.15}
    return rows[0]


def build_opponent_factors(season: str, prior_seasons: list[str], current_gws, prior_gws):
    """Opponent generosity per (current-season team id, position).

    Prior-season rows carry that season's team ids and player ids, both of which
    are reassigned every summer. Opponents are therefore translated through the
    stable club `code`; a relegated club simply drops out.
    """
    cur_players = select("players", f"season=eq.{season}&select=id,element_type")
    position_by_player = {p["id"]: p["element_type"] for p in cur_players}

    cur_teams = select("teams", f"season=eq.{season}&select=id,code")
    code_to_current = {t["code"]: t["id"] for t in cur_teams}

    translated_prior = []
    for prior_season in prior_seasons:
        prior_teams = select("teams", f"season=eq.{prior_season}&select=id,code")
        prior_id_to_code = {t["id"]: t["code"] for t in prior_teams}
        prior_players = select(
            "players", f"season=eq.{prior_season}&select=id,element_type"
        )
        prior_positions = {p["id"]: p["element_type"] for p in prior_players}

        for r in prior_gws:
            if r.get("season") != prior_season:
                continue
            code = prior_id_to_code.get(r.get("opponent_team"))
            current_id = code_to_current.get(code) if code else None
            if current_id is None:
                continue  # club is not in this season's league
            pos = prior_positions.get(r.get("player_id"))
            if not pos:
                continue
            translated_prior.append(
                {
                    "opponent_team": current_id,
                    "player_id": r["player_id"],
                    "minutes": r.get("minutes"),
                    "total_points": r.get("total_points"),
                }
            )
        # Prior-season positions must be resolvable for those rows too.
        position_by_player = {**prior_positions, **position_by_player}

    return opponent_strength.build_factors(
        current_gws, translated_prior, position_by_player, season
    )


def load_inputs(season: str, prior_seasons: list[str]) -> tuple:
    log("  loading players, teams, fixtures")
    players = select("players", f"season=eq.{season}&select=*")
    teams = select("teams", f"season=eq.{season}&select=*")
    fixtures = select("fixtures", f"season=eq.{season}&select=*")

    current_gws = select("player_gameweeks", f"season=eq.{season}&select=*")
    prior_gws: list[dict] = []
    for ps in prior_seasons:
        prior_gws.extend(select("player_gameweeks", f"season=eq.{ps}&select=*"))
    log(
        f"  {len(players)} players, {len(fixtures)} fixtures, "
        f"{len(current_gws)} current-season and {len(prior_gws)} prior-season gameweeks"
    )
    return players, teams, fixtures, current_gws, prior_gws


def next_gameweeks(fixtures: list[dict], horizon: int) -> list[int]:
    """The next `horizon` gameweeks that still have unfinished fixtures."""
    pending = sorted({f["event"] for f in fixtures if f.get("event") and not f["finished"]})
    return pending[:horizon]


def build_predictions(
    season: str,
    players: list[dict],
    teams: list[dict],
    fixtures: list[dict],
    rows_by_code: dict,
    gws: list[int],
    opponent_factors: dict | None = None,
    gate: dict | None = None,
) -> list[dict]:
    """Predicted-points rows for every player across `gws`.

    This is the single scoring path. Both the database pipeline and the offline
    dry run call it, so a dry run that looks right cannot mask a pipeline that
    is wrong.
    """
    team_by_id = {t["id"]: t for t in teams}
    elo_by_team = {t["id"]: t.get("elo") for t in teams}
    rates_by_player = build_player_rates(players, rows_by_code, elo_by_team)

    opponent_factors = opponent_factors or {}
    gate = gate or {"enabled": False, "max_adjustment": 0.15}
    trends_live = bool(gate.get("enabled"))
    gate_cap = float(gate.get("max_adjustment") or 0.15)

    fixtures_by_gw: dict[int, list[dict]] = defaultdict(list)
    for f in fixtures:
        if f.get("event") in gws and not f["finished"]:
            fixtures_by_gw[f["event"]].append(f)

    rows: list[dict] = []
    for gw in gws:
        by_team: dict[int, list[tuple[dict, bool]]] = defaultdict(list)
        for f in fixtures_by_gw[gw]:
            by_team[f["team_h"]].append((f, True))
            by_team[f["team_a"]].append((f, False))

        for p in players:
            rates = rates_by_player[p["id"]]
            avail, avail_reason = availability(p)
            team_fixtures = by_team.get(p["team_id"], [])

            base_total = 0.0
            real_total = 0.0
            trend_total = 0.0
            parts_sum: dict[str, float] = defaultdict(float)
            fixture_detail = []

            for f, is_home in team_fixtures:
                opponent_id = f["team_a"] if is_home else f["team_h"]
                team = team_by_id.get(p["team_id"], {})
                opponent = team_by_id.get(opponent_id, {})

                # Neutral reference: average opponent, neutral venue.
                base = score_fixture(rates, avail, 1.0, LEAGUE_AVG_GOALS_PER_TEAM)
                attack_mult = elo_multiplier(team.get("elo"), opponent.get("elo")) * (
                    HOME_ATTACK_FACTOR if is_home else AWAY_ATTACK_FACTOR
                )
                concede_lam = team_concede_lambda(
                    team.get("elo"), opponent.get("elo"), is_home
                )
                real = score_fixture(rates, avail, attack_mult, concede_lam)

                # How generous this opponent is to this position, in FPL points.
                # Damped and capped in opponent_strength, capped again by the
                # gate, and never applied to forwards.
                factor, factor_detail = opponent_strength.factor_for(
                    opponent_factors, opponent_id, rates["position"]
                )
                if not trends_live:
                    factor = 1.0
                else:
                    factor = max(1.0 - gate_cap, min(1.0 + gate_cap, factor))
                fixture_trend = real["total"] * (factor - 1.0)
                trend_total += fixture_trend

                base_total += base["total"]
                real_total += real["total"]
                for k, v in real.items():
                    if k not in ("total", "p60", "p_any", "expected_minutes"):
                        parts_sum[k] += v
                fixture_detail.append(
                    {
                        "fixture_id": f["id"],
                        "opponent": opponent.get("short_name"),
                        "opponent_elo": opponent.get("elo"),
                        "opponent_elo_source": opponent.get("elo_source"),
                        "is_home": is_home,
                        "attack_multiplier": round(attack_mult, 3),
                        "expected_goals_conceded": round(concede_lam, 3),
                        "clean_sheet_probability": round(poisson_zero(concede_lam), 3),
                        "points": round(real["total"], 3),
                        "opponent_position_factor": round(factor, 4),
                        "opponent_position_detail": factor_detail,
                        "trend_points": round(fixture_trend, 3),
                    }
                )

            first = team_fixtures[0] if team_fixtures else None
            rows.append(
                {
                    "season": season,
                    "player_id": p["id"],
                    "gw": gw,
                    "fixture_id": first[0]["id"] if first else None,
                    "opponent_id": (
                        (first[0]["team_a"] if first[1] else first[0]["team_h"])
                        if first
                        else None
                    ),
                    "was_home": first[1] if first else None,
                    "minutes_probability": round(rates["p60"] * avail, 4),
                    "expected_minutes": round(rates["avg_minutes"] * avail, 2),
                    "base_score": round(base_total, 3),
                    "fixture_adjustment": round(real_total - base_total, 3),
                    "trend_adjustment": round(trend_total, 3),
                    "bps_adjustment": 0,
                    "final_score": round(real_total + trend_total, 3),
                    "model_version": MODEL_VERSION,
                    "confidence_breakdown": {
                        "confidence": confidence_tier(rates),
                        "evidence_90s": rates["evidence_90s"],
                        "current_season_90s": rates["current_90s"],
                        "games_observed": rates["games_observed"],
                        "availability": round(avail, 3),
                        "availability_reason": avail_reason,
                        "depth_rank": rates["depth_rank"],
                        "depth_prior_p60": rates["depth_prior_p60"],
                        "team_prior_scale": rates["team_prior_scale"],
                        "fixtures_this_gw": len(team_fixtures),
                        "components": {k: round(v, 3) for k, v in parts_sum.items()},
                        "rates": {
                            "xg90": round(rates["xg90"], 4),
                            "xa90": round(rates["xa90"], 4),
                            "bonus90": round(rates["bonus90"], 4),
                            "p60": round(rates["p60"], 4),
                            "avg_minutes": round(rates["avg_minutes"], 2),
                            "defcon_rate": round(rates["defcon_rate"], 4),
                        },
                        "fixtures": fixture_detail,
                        "trend_engine": (
                            "opponent generosity by position, damped "
                            f"{opponent_strength.DAMPING}, capped "
                            f"{int(gate_cap * 100)}%"
                            if trends_live
                            else "disabled -- gate closed"
                        ),
                        "notes": [
                            "BPS adjustment held at 0: the BPS system was rewritten "
                            "for 2026/27, so any calibration on 2025/26 data would "
                            "fit the old formula."
                        ],
                    },
                }
            )
    return rows


def main(season: str = CURRENT_SEASON, horizon: int = HORIZON) -> None:
    with Run("predict", season) as run:
        players, teams, fixtures, current_gws, prior_gws = load_inputs(
            season, VAASTAV_SEASONS
        )
        if not players or not fixtures:
            raise RuntimeError("no players or fixtures found -- run ingestion first")

        rows_by_code: dict[int, list[dict]] = defaultdict(list)
        for r in current_gws + prior_gws:
            rows_by_code[r["player_code"]].append(r)

        gws = next_gameweeks(fixtures, horizon)
        if not gws:
            raise RuntimeError("no upcoming gameweeks found in fixtures")
        log(f"  projecting gameweeks {gws}")

        gate = load_gate()
        factors = build_opponent_factors(season, VAASTAV_SEASONS, current_gws, prior_gws)
        log(f"  opponent factors for {len(factors)} team-positions; "
            f"trend gate {'OPEN' if gate.get('enabled') else 'closed'}")

        rows = build_predictions(
            season, players, teams, fixtures, rows_by_code, gws, factors, gate
        )
        run.rows = upsert("predicted_points", rows, on_conflict="season,player_id,gw")
        log(f"  wrote {run.rows} predictions across {len(gws)} gameweeks")


if __name__ == "__main__":
    main()
