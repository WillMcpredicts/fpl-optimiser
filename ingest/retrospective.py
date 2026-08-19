"""What was the best £100m squad last season, with hindsight?

Not a prediction and not a benchmark to beat -- the perfect squad is unknowable
in advance, and any model that got near it would be overfitting. The point is
STRUCTURAL: how a perfect squad spent its money, where it took risk, how much of
the budget went to the bench. Those patterns transfer even though the players do
not.

Prices are the ones you would actually have paid: each player's value in their
first appearance, not their end-of-season price after a season of rises. One
static squad, no transfers, so it answers "what could you have picked in August
and left alone".

Run:  python ingest/retrospective.py [season]
"""
from __future__ import annotations

import statistics
import sys
from collections import defaultdict

import pulp

from common import log, select
from optimiser import FORMATION_MAX, FORMATION_MIN, SQUAD_SHAPE, STARTERS, TEAM_LIMIT
from scoring import DEF, FWD, GK, MID

BUDGET = 1000
POS = {GK: "GKP", DEF: "DEF", MID: "MID", FWD: "FWD"}
MIN_APPEARANCES = 3
SOLVE_SECONDS = 300


def load(season: str):
    players = {
        p["id"]: p
        for p in select("players", f"season=eq.{season}&select=id,web_name,element_type,team_id")
    }
    teams = {
        t["id"]: t["short_name"] for t in select("teams", f"season=eq.{season}&select=id,short_name")
    }
    rows = select("player_gameweeks", f"season=eq.{season}&select=*")

    per_player: dict[int, dict] = defaultdict(lambda: {"gw": {}, "value": None, "apps": 0, "mins": 0})
    for r in rows:
        pid, gw = r["player_id"], r["gw"]
        if pid not in players:
            continue
        d = per_player[pid]
        d["gw"][gw] = d["gw"].get(gw, 0) + (r["total_points"] or 0)
        d["mins"] += r["minutes"] or 0
        if (r["minutes"] or 0) > 0:
            d["apps"] += 1
        # Starting price: the value recorded at their earliest gameweek.
        if r.get("value") and (d["value"] is None or gw < d.get("first_gw", 99)):
            d["value"] = r["value"]
            d["first_gw"] = gw

    pool = []
    for pid, d in per_player.items():
        if d["apps"] < MIN_APPEARANCES or not d["value"]:
            continue
        p = players[pid]
        pool.append({
            "id": pid,
            "name": p["web_name"],
            "pos": p["element_type"],
            "team_id": p["team_id"],
            "team": teams.get(p["team_id"], "?"),
            "cost": d["value"],
            "gw": d["gw"],
            "total": sum(d["gw"].values()),
            "apps": d["apps"],
            "mins": d["mins"],
        })
    gws = sorted({g for p in pool for g in p["gw"]})
    return pool, gws


def optimise(pool: list[dict], gws: list[int]):
    prob = pulp.LpProblem("retro", pulp.LpMaximize)
    ids = [p["id"] for p in pool]
    by_id = {p["id"]: p for p in pool}
    squad = pulp.LpVariable.dicts("s", ids, cat="Binary")
    start = pulp.LpVariable.dicts("x", (ids, gws), cat="Binary")
    capt = pulp.LpVariable.dicts("c", (ids, gws), cat="Binary")

    prob += pulp.lpSum(
        by_id[i]["gw"].get(g, 0) * (start[i][g] + capt[i][g]) for i in ids for g in gws
    )
    prob += pulp.lpSum(squad[i] for i in ids) == 15
    for pos, n in SQUAD_SHAPE.items():
        prob += pulp.lpSum(squad[i] for i in ids if by_id[i]["pos"] == pos) == n
    for t in {p["team_id"] for p in pool}:
        prob += pulp.lpSum(squad[i] for i in ids if by_id[i]["team_id"] == t) <= TEAM_LIMIT
    prob += pulp.lpSum(by_id[i]["cost"] * squad[i] for i in ids) <= BUDGET
    for g in gws:
        prob += pulp.lpSum(start[i][g] for i in ids) == STARTERS
        prob += pulp.lpSum(capt[i][g] for i in ids) == 1
        for pos in SQUAD_SHAPE:
            n = pulp.lpSum(start[i][g] for i in ids if by_id[i]["pos"] == pos)
            prob += n >= FORMATION_MIN[pos]
            prob += n <= FORMATION_MAX[pos]
        for i in ids:
            prob += start[i][g] <= squad[i]
            prob += capt[i][g] <= start[i][g]

    status = prob.solve(pulp.PULP_CBC_CMD(msg=0, timeLimit=SOLVE_SECONDS))
    chosen = [by_id[i] for i in ids if squad[i].value() and squad[i].value() > 0.5]
    started = {
        i: sum(1 for g in gws if start[i][g].value() and start[i][g].value() > 0.5)
        for i in [p["id"] for p in chosen]
    }
    capped = {
        i: sum(1 for g in gws if capt[i][g].value() and capt[i][g].value() > 0.5)
        for i in [p["id"] for p in chosen]
    }
    return chosen, started, capped, pulp.value(prob.objective), pulp.LpStatus[status]


def main(season: str = "2025-26") -> None:
    pool, gws = load(season)
    log(f"  {len(pool)} players with {MIN_APPEARANCES}+ appearances, {len(gws)} gameweeks")
    chosen, started, capped, total, status = optimise(pool, gws)
    log(f"  solver: {status}\n")

    cost = sum(p["cost"] for p in chosen)
    print(f"  Best static £100m squad for {season}: {total:.0f} points, cost £{cost/10:.1f}m\n")
    print(f"  {'Player':<16}{'Tm':<5}{'Pos':<5}{'£ start':>9}{'Points':>8}{'Started':>9}{'Capt':>6}{'Pts/£m':>9}")
    print("  " + "-" * 68)
    for p in sorted(chosen, key=lambda x: (x["pos"], -x["total"])):
        print(f"  {p['name'][:15]:<16}{p['team']:<5}{POS[p['pos']]:<5}{p['cost']/10:>9.1f}"
              f"{p['total']:>8.0f}{started.get(p['id'],0):>9}{capped.get(p['id'],0):>6}"
              f"{p['total']/(p['cost']/10):>9.1f}")

    print("\n  What it did with the money")
    by_pos = defaultdict(list)
    for p in chosen:
        by_pos[p["pos"]].append(p)
    for pos in (GK, DEF, MID, FWD):
        ps = by_pos[pos]
        spend = sum(x["cost"] for x in ps)
        pts = sum(x["total"] for x in ps)
        print(f"    {POS[pos]}: £{spend/10:>5.1f}m ({spend/cost*100:>4.1f}% of budget) "
              f"-> {pts:>4.0f} pts ({pts/total*100:>4.1f}% of total)")

    bench_ish = [p for p in chosen if started.get(p["id"], 0) < len(gws) * 0.25]
    print(f"\n    {len(bench_ish)} player(s) started under a quarter of gameweeks, "
          f"costing £{sum(p['cost'] for p in bench_ish)/10:.1f}m in total")
    prices = sorted(p["cost"] for p in chosen)
    print(f"    cheapest £{prices[0]/10:.1f}m, dearest £{prices[-1]/10:.1f}m, "
          f"median £{statistics.median(prices)/10:.1f}m")
    premium = [p for p in chosen if p["cost"] >= 90]
    print(f"    {len(premium)} player(s) at £9.0m or more, taking "
          f"£{sum(p['cost'] for p in premium)/10:.1f}m and returning "
          f"{sum(p['total'] for p in premium):.0f} points")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "2025-26")
