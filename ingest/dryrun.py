"""Run the Phase 1 model against live sources, in memory, with no database.

Two jobs:

  * verify the model before Supabase exists, or after a change to the maths;
  * write data/snapshot.json, which the Next.js app falls back to when the
    database is not configured -- so the predicted points table is viewable
    on day one.

It calls model.build_predictions(), the same function the real pipeline uses,
so this cannot pass while the pipeline is broken.

    python ingest/dryrun.py [horizon] [--top N] [--position MID] [--snapshot]
"""
from __future__ import annotations

import json
import pathlib
import sys
from collections import defaultdict
from datetime import datetime, timezone

import elo as elo_mod
import fpl as fpl_mod
import history as history_mod
import model as model_mod
from common import get_csv, get_json, log, to_float, to_int
from config import CURRENT_SEASON, FPL_API, VAASTAV_RAW, VAASTAV_SEASONS

POSITION_NAMES = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}
SNAPSHOT_PATH = pathlib.Path(__file__).resolve().parent.parent / "data" / "snapshot.json"


def gather():
    log("fetching FPL bootstrap-static")
    boot = fpl_mod.fetch_bootstrap()
    log("resolving team Elo")
    elo, elo_source = elo_mod.resolve(CURRENT_SEASON, boot["teams"])
    log("fetching fixtures")
    fixtures_raw = get_json(f"{FPL_API}/fixtures/")

    teams = fpl_mod.build_teams(boot, elo, elo_source, CURRENT_SEASON)
    players = fpl_mod.build_players(boot, CURRENT_SEASON)
    fixtures = fpl_mod.build_fixtures(fixtures_raw, CURRENT_SEASON)

    prior_by_code: dict[int, list[dict]] = defaultdict(list)
    for season in VAASTAV_SEASONS:
        log(f"fetching {season} history from the vaastav archive")
        rows = get_csv(f"{VAASTAV_RAW}/{season}/gws/merged_gw.csv")
        codes = history_mod.code_map(season)
        for r in history_mod.build_gameweeks(season, rows, codes):
            prior_by_code[r["player_code"]].append(r)

    current_by_code: dict[int, list[dict]] = defaultdict(list)
    finished = [e["id"] for e in boot["events"] if e.get("finished")]
    if finished:
        log(f"fetching {len(finished)} finished gameweeks of live data")
        code_by_id = {e["id"]: e["code"] for e in boot["elements"]}
        for gw in finished:
            live = get_json(f"{FPL_API}/event/{gw}/live/")
            for el in live.get("elements", []):
                s = el["stats"]
                current_by_code[code_by_id[el["id"]]].append(
                    {
                        "minutes": to_int(s.get("minutes")),
                        "starts": to_int(s.get("starts")),
                        "bonus": to_int(s.get("bonus")),
                        "saves": to_int(s.get("saves")),
                        "yellow_cards": to_int(s.get("yellow_cards")),
                        "expected_goals": to_float(s.get("expected_goals")),
                        "expected_assists": to_float(s.get("expected_assists")),
                        "defensive_contribution": to_int(s.get("defensive_contribution")),
                    }
                )
    else:
        log("no finished gameweeks this season -- projecting from priors alone")
    return boot, teams, players, fixtures, current_by_code, prior_by_code


def write_snapshot(teams, players, rows, warnings) -> None:
    SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()
    payload = {
        "generated_at": now,
        "model_version": model_mod.MODEL_VERSION,
        "season": CURRENT_SEASON,
        "warnings": warnings,
        "teams": [{"id": t["id"], "short_name": t["short_name"]} for t in teams],
        "players": [
            {
                "id": p["id"],
                "web_name": p["web_name"],
                "team_id": p["team_id"],
                "element_type": p["element_type"],
                "now_cost": p["now_cost"],
                "status": p["status"],
                "news": p["news"],
                "selected_by_percent": p["selected_by_percent"],
            }
            for p in players
        ],
        "predictions": [{**r, "computed_at": now} for r in rows],
    }
    SNAPSHOT_PATH.write_text(json.dumps(payload))
    size_kb = SNAPSHOT_PATH.stat().st_size / 1024
    log(f"\nsnapshot written: {SNAPSHOT_PATH} ({size_kb:.0f} KB)")


def parse_args(argv: list[str]) -> tuple[int, str | None, int, bool]:
    horizon, position, top, snapshot = 3, None, 25, False
    skip: set[int] = set()
    for i, a in enumerate(argv):
        if i in skip:
            continue
        if a == "--position" and i + 1 < len(argv):
            position = argv[i + 1].upper()
            skip.add(i + 1)
        elif a == "--top" and i + 1 < len(argv):
            top = int(argv[i + 1])
            skip.add(i + 1)
        elif a == "--snapshot":
            snapshot = True
        elif a.isdigit():
            horizon = int(a)
    return horizon, position, top, snapshot


def main() -> None:
    horizon, position_filter, top, snapshot = parse_args(sys.argv[1:])

    boot, teams, players, fixtures, current_by_code, prior_by_code = gather()
    gws = model_mod.next_gameweeks(fixtures, horizon)
    log(f"\nprojecting gameweeks {gws}\n")

    rows = model_mod.build_predictions(
        CURRENT_SEASON, players, teams, fixtures, current_by_code, prior_by_code, gws
    )

    warnings: list[str] = []
    sources = {t.get("elo_source") for t in teams}
    if "promoted_side_prior" in sources:
        promoted = [t["short_name"] for t in teams if t.get("elo_source") == "promoted_side_prior"]
        warnings.append(
            f"No Elo history for {', '.join(promoted)}; a promoted-side prior was used."
        )
    if not any(e.get("finished") for e in boot["events"]):
        warnings.append(
            "No gameweeks played yet this season -- every rate comes from 2025/26 priors."
        )

    if snapshot:
        write_snapshot(teams, players, rows, warnings)

    # Console view.
    team_name = {t["id"]: t["short_name"] for t in teams}
    player_by_id = {p["id"]: p for p in players}
    agg: dict[int, dict] = {}
    for r in rows:
        p = player_by_id[r["player_id"]]
        a = agg.setdefault(
            r["player_id"],
            {
                "name": p["web_name"],
                "team": team_name.get(p["team_id"], "?"),
                "pos": POSITION_NAMES[p["element_type"]],
                "price": (p["now_cost"] or 0) / 10.0,
                "per_gw": {},
                "total": 0.0,
                "base": 0.0,
                "mins": r["expected_minutes"],
                "conf": r["confidence_breakdown"]["confidence"],
            },
        )
        a["per_gw"][r["gw"]] = r["final_score"]
        a["total"] += r["final_score"]
        a["base"] += r["base_score"]

    results = list(agg.values())
    if position_filter:
        results = [r for r in results if r["pos"] == position_filter]
    results.sort(key=lambda r: r["total"], reverse=True)

    head = f"{'Player':<16}{'Tm':<5}{'Pos':<5}{'£':>6}"
    for gw in gws:
        head += f"{'GW' + str(gw):>7}"
    head += f"{'Tot':>8}{'Base':>8}{'Fix':>7}{'xMin':>7}{'Conf':>7}"
    print(head)
    print("-" * len(head))
    for r in results[:top]:
        line = f"{r['name'][:15]:<16}{r['team']:<5}{r['pos']:<5}{r['price']:>6.1f}"
        for gw in gws:
            line += f"{r['per_gw'].get(gw, 0):>7.2f}"
        line += (
            f"{r['total']:>8.2f}{r['base']:>8.2f}{r['total'] - r['base']:>+7.2f}"
            f"{r['mins']:>7.0f}{r['conf']:>7}"
        )
        print(line)

    print(f"\n{len(results)} players scored across gameweeks {gws}.")
    for w in warnings:
        print(f"  warning: {w}")


if __name__ == "__main__":
    main()
