"""When to play Bench Boost and Triple Captain.

Both are worth points only in the right week, and the right week is knowable in
advance from the fixture list:

  Bench Boost   your four bench players score for real, so the best week is the
                one where the bench projects highest -- typically a week where
                everyone has a fixture and the cheap enablers face weak sides.

  Triple Captain  the captain scores triple rather than double, so the value is
                  one EXTRA copy of your best single projected score.

Two of each per season, one per half. This plans the current half only, from the
squad as it stands, and is advisory -- a squad changes, and so does the answer.

Wildcard and Free Hit are deliberately not planned here. Their value depends on
what you would transfer to, which is the optimiser's job, and pretending to
price them from the current squad alone would be misleading.
"""
from __future__ import annotations

from collections import defaultdict

from common import Run, delete_where, insert_rows, log, select
from config import CURRENT_SEASON
from planner import best_xi, build_squad_view, load_context

CHIPS = {"bboost": "Bench Boost", "3xc": "Triple Captain"}


def evaluate(season: str = CURRENT_SEASON, horizon: int = 6) -> list[dict]:
    squad_row, picks, universe, gws = load_context(season, horizon)
    squad = build_squad_view(picks, universe)
    if len(squad) < 15:
        log(f"  squad has {len(squad)} scored players; chip values will be understated")

    rows: list[dict] = []
    per_chip: dict[str, list[tuple[int, float, dict]]] = defaultdict(list)

    for gw in gws:
        # Rank this gameweek only -- the XI you would field that week.
        for p in squad:
            p["points_3gw"] = p["per_gw"].get(gw, 0.0)
        starters, bench = best_xi(squad)

        bench_points = sum(p["per_gw"].get(gw, 0.0) for p in bench)
        best_starter = max((p["per_gw"].get(gw, 0.0) for p in starters), default=0.0)
        captain = max(starters, key=lambda p: p["per_gw"].get(gw, 0.0), default=None)

        per_chip["bboost"].append((gw, bench_points, {
            "bench": [
                {"name": p["web_name"], "team": p["team"],
                 "points": round(p["per_gw"].get(gw, 0.0), 2)}
                for p in sorted(bench, key=lambda x: -x["per_gw"].get(gw, 0.0))
            ],
        }))
        per_chip["3xc"].append((gw, best_starter, {
            "captain": captain["web_name"] if captain else None,
            "team": captain["team"] if captain else None,
            "points": round(best_starter, 2),
        }))

    for chip, entries in per_chip.items():
        best_gw = max(entries, key=lambda e: e[1])[0]
        for gw, value, detail in entries:
            rows.append({
                "season": season,
                "chip": chip,
                "gw": gw,
                "value_points": round(value, 3),
                "detail": detail,
                "is_best": gw == best_gw,
            })
    return rows


def main() -> None:
    season = CURRENT_SEASON
    if not select("my_squad", f"season=eq.{season}&is_current=is.true&select=id"):
        log("[chips] no squad imported yet; nothing to plan")
        return
    with Run("chips", season) as run:
        rows = evaluate(season)
        delete_where("chip_plans", f"season=eq.{season}")
        run.rows = insert_rows("chip_plans", rows)
        for chip, label in CHIPS.items():
            entries = sorted(
                (r for r in rows if r["chip"] == chip),
                key=lambda r: -r["value_points"],
            )
            if entries:
                top = entries[0]
                extra = (
                    f"bench projects {top['value_points']:.2f}"
                    if chip == "bboost"
                    else f"{top['detail'].get('captain')} adds {top['value_points']:.2f}"
                )
                log(f"  {label}: best in GW{top['gw']} -- {extra}")


if __name__ == "__main__":
    main()
