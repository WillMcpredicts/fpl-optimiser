"""Ingest shot-level and team-match data from FPL-Core-Insights.

This is what the trend engine reads. Two things the source needs care with:

  * Shot rows carry no team id -- only `is_home` and `match_id`. Team and
    opponent come from matches.csv, and shooter position from players.csv.
  * The files mix competitions. Only `tournament == 'prem'` rows have usable
    FPL team ids; the rest (Champions League, Europa, Conference, EFL Cup)
    have blanks and must be dropped, or European fixtures will silently
    pollute Premier League defensive rates.

Shot-level data exists for 2025-26 onwards only. 2024-25 has matches.csv but
no shots.csv, so zonal and body-part trends cannot go back further.
"""
from __future__ import annotations

import sys
from collections import defaultdict

from common import Run, get_csv, log, to_float, to_int, upsert
from config import CORE_INSIGHTS_RAW, core_insights_season

# Shot origin coordinates are 0-100 across the pitch. `start_x` is distance
# from goal, `start_y` runs across it.
def zone_of(start_x: float | None, start_y: float | None) -> str:
    if start_x is None or start_y is None:
        return "unknown"
    depth = "six_yard" if start_x < 6 else "penalty_area" if start_x < 18 else "outside_box"
    if start_y < 36:
        side = "right"
    elif start_y > 64:
        side = "left"
    else:
        side = "central"
    return f"{depth}_{side}"


def fetch_gameweek(season: str, gw: int) -> tuple[list[dict], list[dict], list[dict]]:
    ci = core_insights_season(season)
    base = f"{CORE_INSIGHTS_RAW}/{ci}/By%20Gameweek/GW{gw}"
    matches = get_csv(f"{base}/matches.csv", required=False)
    shots = get_csv(f"{base}/shots.csv", required=False)
    players = get_csv(f"{base}/players.csv", required=False)
    return matches, shots, players


def build_team_match_stats(season: str, matches: list[dict]) -> list[dict]:
    """One row per team per match, so rates have their denominators to hand."""
    rows: list[dict] = []
    for m in matches:
        if "prem" not in (m.get("tournament") or "").lower():
            continue
        home_id, away_id = to_int(m.get("home_team"), None), to_int(m.get("away_team"), None)
        if not home_id or not away_id:
            continue
        gw = to_int(m.get("gameweek"), None)
        for is_home, tid, oid in ((True, home_id, away_id), (False, away_id, home_id)):
            me, them = ("home", "away") if is_home else ("away", "home")
            rows.append(
                {
                    "season": season,
                    "match_id": m["match_id"],
                    "team_id": tid,
                    "opponent_id": oid,
                    "gw": gw,
                    "kickoff_time": m.get("kickoff_time") or None,
                    "is_home": is_home,
                    "elo": to_float(m.get(f"{me}_team_elo")),
                    "opponent_elo": to_float(m.get(f"{them}_team_elo")),
                    "goals_for": to_int(m.get(f"{me}_score"), None),
                    "goals_against": to_int(m.get(f"{them}_score"), None),
                    "xg": to_float(m.get(f"{me}_expected_goals_xg")),
                    "xg_conceded": to_float(m.get(f"{them}_expected_goals_xg")),
                    "xg_open_play": to_float(m.get(f"{me}_xg_open_play")),
                    "xg_set_play": to_float(m.get(f"{me}_xg_set_play")),
                    "non_penalty_xg": to_float(m.get(f"{me}_non_penalty_xg")),
                    "shots": to_int(m.get(f"{me}_total_shots"), None),
                    "shots_on_target": to_int(m.get(f"{me}_shots_on_target"), None),
                    "shots_inside_box": to_int(m.get(f"{me}_shots_inside_box"), None),
                    "shots_outside_box": to_int(m.get(f"{me}_shots_outside_box"), None),
                    "big_chances": to_int(m.get(f"{me}_big_chances"), None),
                    "corners": to_int(m.get(f"{me}_corners"), None),
                    "crosses_accurate": to_int(m.get(f"{me}_accurate_crosses"), None),
                    "aerial_duels_won": to_int(m.get(f"{me}_aerial_duels_won"), None),
                    "aerial_duels_won_pct": to_float(m.get(f"{me}_aerial_duels_won_pct")),
                    "ground_duels_won": to_int(m.get(f"{me}_ground_duels_won"), None),
                    "tackles_won": to_int(m.get(f"{me}_tackles_won"), None),
                    "interceptions": to_int(m.get(f"{me}_interceptions"), None),
                    "clearances": to_int(m.get(f"{me}_clearances"), None),
                    "blocks": to_int(m.get(f"{me}_blocks"), None),
                    "keeper_saves": to_int(m.get(f"{me}_keeper_saves"), None),
                    "touches_in_opp_box": to_int(m.get(f"{me}_touches_in_opposition_box"), None),
                }
            )
    return rows


def build_match_events(
    season: str, matches: list[dict], shots: list[dict], players: list[dict]
) -> list[dict]:
    """Shot rows, resolved to team/opponent and shooter position."""
    match_by_id = {}
    for m in matches:
        if "prem" not in (m.get("tournament") or "").lower():
            continue
        h, a = to_int(m.get("home_team"), None), to_int(m.get("away_team"), None)
        if h and a:
            match_by_id[m["match_id"]] = {
                "home": h,
                "away": a,
                "gw": to_int(m.get("gameweek"), None),
                "kickoff": m.get("kickoff_time") or None,
            }

    position_by_pid = {
        to_int(p["player_id"]): p.get("position") for p in players if p.get("player_id")
    }
    code_by_pid = {
        to_int(p["player_id"]): to_int(p.get("player_code"), None)
        for p in players
        if p.get("player_id")
    }

    rows: list[dict] = []
    for s in shots:
        meta = match_by_id.get(s.get("match_id"))
        if not meta:
            continue  # not a Premier League match
        is_home = str(s.get("is_home", "")).strip().lower() == "true"
        team_id = meta["home"] if is_home else meta["away"]
        opponent_id = meta["away"] if is_home else meta["home"]
        pid = to_int(s.get("player_id"), None)
        start_x, start_y = to_float(s.get("start_x")), to_float(s.get("start_y"))
        rows.append(
            {
                "season": season,
                "match_id": s["match_id"],
                "shot_index": to_int(s.get("shot_index")),
                "gw": meta["gw"],
                "kickoff_time": meta["kickoff"],
                "team_id": team_id,
                "opponent_id": opponent_id,
                "is_home": is_home,
                "player_id": pid,
                "player_code": code_by_pid.get(pid),
                "player_position": position_by_pid.get(pid),
                "minute": to_int(s.get("minute"), None),
                "body_part": s.get("body_part") or None,
                "situation": s.get("situation") or None,
                "zone": zone_of(start_x, start_y),
                "start_x": start_x,
                "start_y": start_y,
                "xg": to_float(s.get("xg")),
                "xgot": to_float(s.get("xgot")),
                "outcome": s.get("outcome") or None,
                "is_goal": (s.get("outcome") or "").lower() == "goal",
            }
        )
    return rows


def collect(season: str, max_gw: int = 38) -> tuple[list[dict], list[dict]]:
    """Fetch every gameweek for a season. Returns (team_match_stats, match_events)."""
    tms: list[dict] = []
    events: list[dict] = []
    for gw in range(1, max_gw + 1):
        matches, shots, players = fetch_gameweek(season, gw)
        if not matches:
            continue
        t = build_team_match_stats(season, matches)
        e = build_match_events(season, matches, shots, players) if shots else []
        tms.extend(t)
        events.extend(e)
        if t or e:
            log(f"  GW{gw}: {len(t)} team-match rows, {len(e)} shots")
    return tms, events


def main(season: str = "2025-26") -> None:
    with Run("core_insights_shots", season) as run:
        tms, events = collect(season)
        log(f"  total: {len(tms)} team-match rows, {len(events)} shot events")
        run.rows += upsert("team_match_stats", tms, on_conflict="season,match_id,team_id")
        run.rows += upsert(
            "match_events", events, on_conflict="season,match_id,shot_index"
        )


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "2025-26")
