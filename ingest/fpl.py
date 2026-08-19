"""Ingest the live FPL API: teams, players, fixtures.

Team Elo is not in the FPL API, so it is layered on from FPL-Core-Insights'
teams.csv (which is FPL-id-aligned already). If that file is unavailable the
job still succeeds with elo left null -- the predictor falls back to FPL's own
strength ratings rather than failing the whole run.
"""
from __future__ import annotations

import elo as elo_mod
from common import Run, get_json, log, to_float, to_int, upsert
from config import CURRENT_SEASON, FPL_API


def fetch_bootstrap() -> dict:
    return get_json(f"{FPL_API}/bootstrap-static/")


def build_teams(
    boot: dict,
    elo: dict[int, float],
    elo_source: dict[int, str],
    season: str,
) -> list[dict]:
    return [
        {
            "season": season,
            "id": t["id"],
            "code": t["code"],
            "name": t["name"],
            "short_name": t["short_name"],
            "strength": t.get("strength"),
            "strength_overall_home": t.get("strength_overall_home"),
            "strength_overall_away": t.get("strength_overall_away"),
            "strength_attack_home": t.get("strength_attack_home"),
            "strength_attack_away": t.get("strength_attack_away"),
            "strength_defence_home": t.get("strength_defence_home"),
            "strength_defence_away": t.get("strength_defence_away"),
            "elo": elo.get(t["id"]),
            "elo_source": elo_source.get(t["id"]),
        }
        for t in boot["teams"]
    ]


def build_players(boot: dict, season: str) -> list[dict]:
    return [
        {
            "season": season,
            "id": e["id"],
            "code": e["code"],
            "first_name": e.get("first_name"),
            "second_name": e.get("second_name"),
            "web_name": e["web_name"],
            "team_id": e["team"],
            "element_type": e["element_type"],
            "now_cost": e.get("now_cost"),
            "status": e.get("status"),
            "news": e.get("news") or None,
            "chance_of_playing_next_round": e.get("chance_of_playing_next_round"),
            "selected_by_percent": to_float(e.get("selected_by_percent")),
            "minutes": to_int(e.get("minutes")),
            "starts": to_int(e.get("starts")),
            "total_points": to_int(e.get("total_points")),
            "bonus": to_int(e.get("bonus")),
            "bps": to_int(e.get("bps")),
            "goals_scored": to_int(e.get("goals_scored")),
            "assists": to_int(e.get("assists")),
            "clean_sheets": to_int(e.get("clean_sheets")),
            "goals_conceded": to_int(e.get("goals_conceded")),
            "saves": to_int(e.get("saves")),
            "expected_goals": to_float(e.get("expected_goals")),
            "expected_assists": to_float(e.get("expected_assists")),
            "expected_goals_conceded": to_float(e.get("expected_goals_conceded")),
            "defensive_contribution": to_int(e.get("defensive_contribution")),
        }
        for e in boot["elements"]
    ]


def build_fixtures(fixtures: list[dict], season: str) -> list[dict]:
    return [
        {
            "season": season,
            "id": f["id"],
            "event": f.get("event"),
            "kickoff_time": f.get("kickoff_time"),
            "team_h": f["team_h"],
            "team_a": f["team_a"],
            "team_h_difficulty": f.get("team_h_difficulty"),
            "team_a_difficulty": f.get("team_a_difficulty"),
            "team_h_score": f.get("team_h_score"),
            "team_a_score": f.get("team_a_score"),
            "finished": bool(f.get("finished")),
        }
        for f in fixtures
    ]


def ingest_live_gameweeks(boot: dict, season: str) -> int:
    """Per-player actuals for gameweeks already played this season.

    Pre-season this writes nothing, which is correct: there is no live data yet
    and the model leans entirely on the historical priors.
    """
    finished = [e["id"] for e in boot["events"] if e.get("finished")]
    if not finished:
        log("  no finished gameweeks yet this season")
        return 0

    code_by_id = {e["id"]: e["code"] for e in boot["elements"]}
    rows: list[dict] = []
    for gw in finished:
        live = get_json(f"{FPL_API}/event/{gw}/live/")
        for el in live.get("elements", []):
            pid = el["id"]
            for ex in el.get("explain", []) or [{}]:
                fixture_id = ex.get("fixture")
                if fixture_id is None:
                    continue
                s = el["stats"]
                rows.append(
                    {
                        "season": season,
                        "player_id": pid,
                        "player_code": code_by_id.get(pid, 0),
                        "gw": gw,
                        "fixture_id": fixture_id,
                        "minutes": to_int(s.get("minutes")),
                        "starts": to_int(s.get("starts")),
                        "total_points": to_int(s.get("total_points")),
                        "bonus": to_int(s.get("bonus")),
                        "bps": to_int(s.get("bps")),
                        "goals_scored": to_int(s.get("goals_scored")),
                        "assists": to_int(s.get("assists")),
                        "clean_sheets": to_int(s.get("clean_sheets")),
                        "goals_conceded": to_int(s.get("goals_conceded")),
                        "saves": to_int(s.get("saves")),
                        "expected_goals": to_float(s.get("expected_goals")),
                        "expected_assists": to_float(s.get("expected_assists")),
                        "expected_goals_conceded": to_float(s.get("expected_goals_conceded")),
                        "defensive_contribution": to_int(s.get("defensive_contribution")),
                        "yellow_cards": to_int(s.get("yellow_cards")),
                        "red_cards": to_int(s.get("red_cards")),
                    }
                )
        log(f"  GW{gw}: {len(rows)} cumulative rows")
    return upsert(
        "player_gameweeks", rows, on_conflict="season,player_id,gw,fixture_id"
    )


def main(season: str = CURRENT_SEASON) -> None:
    with Run("fpl_api", season) as run:
        boot = fetch_bootstrap()
        elo, elo_source = elo_mod.resolve(season, boot["teams"])

        run.rows += upsert(
            "teams",
            build_teams(boot, elo, elo_source, season),
            on_conflict="season,id",
        )
        run.rows += upsert(
            "players", build_players(boot, season), on_conflict="season,id"
        )
        fixtures = get_json(f"{FPL_API}/fixtures/")
        run.rows += upsert(
            "fixtures", build_fixtures(fixtures, season), on_conflict="season,id"
        )
        run.rows += ingest_live_gameweeks(boot, season)


if __name__ == "__main__":
    main()
