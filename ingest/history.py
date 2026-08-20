"""Backfill past seasons from the vaastav archive.

This is what the model stands on before the new season has any data of its own.
merged_gw.csv is one row per player per gameweek for a completed season, which
is exactly the shape player_gameweeks wants.

The season's own players_raw.csv supplies the id -> code mapping. That mapping
is the whole point: `element` in merged_gw is a 2025-26 id and will belong to a
different footballer in 2026-27, so anything crossing a season boundary must
travel by code.
"""
from __future__ import annotations

from common import Run, get_csv, log, to_float, to_int, upsert
from config import VAASTAV_RAW, VAASTAV_SEASONS


def code_map(season: str) -> dict[int, int]:
    rows = get_csv(f"{VAASTAV_RAW}/{season}/players_raw.csv")
    return {to_int(r["id"]): to_int(r["code"]) for r in rows if r.get("id")}


def build_gameweeks(season: str, rows: list[dict], codes: dict[int, int]) -> list[dict]:
    out: list[dict] = []
    missing_code = 0
    for r in rows:
        pid = to_int(r.get("element"), None)
        gw = to_int(r.get("GW"), None)
        fid = to_int(r.get("fixture"), None)
        if pid is None or gw is None or fid is None:
            continue
        code = codes.get(pid)
        if code is None:
            missing_code += 1
            continue
        out.append(
            {
                "season": season,
                "player_id": pid,
                "player_code": code,
                "gw": gw,
                "fixture_id": fid,
                "opponent_team": to_int(r.get("opponent_team"), None),
                "was_home": str(r.get("was_home", "")).lower() == "true",
                "kickoff_time": r.get("kickoff_time") or None,
                "minutes": to_int(r.get("minutes")),
                "starts": to_int(r.get("starts")),
                "total_points": to_int(r.get("total_points")),
                "bonus": to_int(r.get("bonus")),
                "bps": to_int(r.get("bps")),
                "goals_scored": to_int(r.get("goals_scored")),
                "assists": to_int(r.get("assists")),
                "clean_sheets": to_int(r.get("clean_sheets")),
                "goals_conceded": to_int(r.get("goals_conceded")),
                "saves": to_int(r.get("saves")),
                "expected_goals": to_float(r.get("expected_goals")),
                "expected_assists": to_float(r.get("expected_assists")),
                "expected_goals_conceded": to_float(r.get("expected_goals_conceded")),
                "defensive_contribution": to_int(r.get("defensive_contribution"), None),
                "yellow_cards": to_int(r.get("yellow_cards")),
                "red_cards": to_int(r.get("red_cards")),
                "value": to_int(r.get("value"), None),
                "transfers_in": to_int(r.get("transfers_in"), None),
                "transfers_out": to_int(r.get("transfers_out"), None),
                "transfers_balance": to_int(r.get("transfers_balance"), None),
                "selected": to_int(r.get("selected"), None),
            }
        )
    if missing_code:
        log(f"  {missing_code} rows dropped: no code mapping for that element id")
    return out


def ingest_season(season: str) -> int:
    log(f"  fetching {season} merged_gw.csv")
    rows = get_csv(f"{VAASTAV_RAW}/{season}/gws/merged_gw.csv")
    codes = code_map(season)
    built = build_gameweeks(season, rows, codes)
    log(f"  {season}: {len(built)} player-gameweeks from {len(rows)} source rows")
    return upsert(
        "player_gameweeks", built, on_conflict="season,player_id,gw,fixture_id"
    )


def ingest_teams(season: str) -> int:
    rows = get_csv(f"{VAASTAV_RAW}/{season}/teams.csv")
    built = [
        {
            "season": season,
            "id": to_int(r["id"]),
            "code": to_int(r["code"]),
            "name": r["name"],
            "short_name": r["short_name"],
            "strength": to_int(r.get("strength"), None),
            "strength_overall_home": to_int(r.get("strength_overall_home"), None),
            "strength_overall_away": to_int(r.get("strength_overall_away"), None),
            "strength_attack_home": to_int(r.get("strength_attack_home"), None),
            "strength_attack_away": to_int(r.get("strength_attack_away"), None),
            "strength_defence_home": to_int(r.get("strength_defence_home"), None),
            "strength_defence_away": to_int(r.get("strength_defence_away"), None),
        }
        for r in rows
        if r.get("id")
    ]
    return upsert("teams", built, on_conflict="season,id")


def ingest_players(season: str) -> int:
    rows = get_csv(f"{VAASTAV_RAW}/{season}/players_raw.csv")
    built = [
        {
            "season": season,
            "id": to_int(r["id"]),
            "code": to_int(r["code"]),
            "first_name": r.get("first_name"),
            "second_name": r.get("second_name"),
            "web_name": r.get("web_name") or "",
            "team_id": to_int(r.get("team")),
            "element_type": to_int(r.get("element_type")),
            "now_cost": to_int(r.get("now_cost"), None),
            "minutes": to_int(r.get("minutes")),
            "starts": to_int(r.get("starts")),
            "total_points": to_int(r.get("total_points")),
            "expected_goals": to_float(r.get("expected_goals")),
            "expected_assists": to_float(r.get("expected_assists")),
            "expected_goals_conceded": to_float(r.get("expected_goals_conceded")),
            # Set-piece duties, so the penalty premium can be measured on past
            # seasons rather than assumed. Note the archive stores an
            # END-OF-SEASON snapshot, so treat it as approximate for mid-season
            # gameweeks -- duties do change hands.
            "penalties_order": to_int(r.get("penalties_order"), None),
            "penalties_text": r.get("penalties_text") or None,
            "direct_fk_order": to_int(r.get("direct_freekicks_order"), None),
            "corners_fk_order": to_int(
                r.get("corners_and_indirect_freekicks_order"), None
            ),
        }
        for r in rows
        if r.get("id") and r.get("code")
    ]
    return upsert("players", built, on_conflict="season,id")


def main(seasons: list[str] | None = None) -> None:
    for season in seasons or VAASTAV_SEASONS:
        with Run("vaastav_history", season) as run:
            run.rows += ingest_teams(season)
            run.rows += ingest_players(season)
            run.rows += ingest_season(season)


if __name__ == "__main__":
    main()
