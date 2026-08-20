"""Plan transfers across the whole horizon, not one week at a time.

The single-week optimiser answers "what is the best squad I can reach right
now". This answers a harder and more useful question: given one free transfer a
week, bankable up to five, and -4 for anything beyond, what SEQUENCE of moves
maximises starting-XI points across six gameweeks?

They are not the same problem. A transfer that looks marginal this week can be
clearly worth it if the player keeps delivering for five more; a transfer that
looks good now can be wasted if you would rather spend the free transfer next
week on a better target. Only a multi-period model sees that.

Formulated as one mixed-integer program over all six gameweeks at once:

  squad[i][t]   is player i in the squad in gameweek t
  in/out[i][t]  transfers, which move the squad from one week to the next
  free[t]       banked free transfers, gaining one a week, capped at five
  hits[t]       transfers beyond the free ones, at -4 each

Prices are held constant across the horizon. Modelling rises and falls would add
noise to a plan that is already advisory, and the effect over six weeks is small
next to the points.
"""
from __future__ import annotations

import sys
from collections import defaultdict

import pulp

from common import Run, delete_where, insert_rows, log, select
from config import CURRENT_SEASON
from optimiser import (FORMATION_MAX, FORMATION_MIN, SQUAD_SHAPE, STARTERS,
                       TEAM_LIMIT, AUTOSUB_WEIGHT, load_players)
from scoring import DEF, FWD, GK, MID

HIT_COST = 4
MAX_FREE = 5
POOL_SIZE = 160          # top prospects by horizon points, plus the squad
SOLVE_SECONDS = 420
POS = {GK: "GKP", DEF: "DEF", MID: "MID", FWD: "FWD"}


def build_pool(season: str, horizon: int):
    pool, gws = load_players(season, horizon)
    squads = select("my_squad", f"season=eq.{season}&is_current=is.true&select=*")
    if not squads:
        raise RuntimeError("no current squad -- import one first")
    squad_row = squads[0]
    picks = select("my_squad_picks", f"squad_id=eq.{squad_row['id']}&select=*")
    selling = {p["player_id"]: p["selling_price"] for p in picks}

    by_id = {p["id"]: p for p in pool}
    # Keep the best prospects plus everyone currently owned, so the model can
    # always represent "keep him" as well as "sell him".
    ranked = sorted(pool, key=lambda p: -p["total"])[:POOL_SIZE]
    keep_ids = {p["id"] for p in ranked} | set(selling)
    trimmed = [by_id[i] for i in keep_ids if i in by_id]
    missing = set(selling) - {p["id"] for p in trimmed}
    if missing:
        log(f"  {len(missing)} owned player(s) have no projection; treated as sellable only")
    return trimmed, gws, squad_row, selling


def solve(pool, gws, squad_row, selling, horizon_hits: bool = True):
    ids = [p["id"] for p in pool]
    by = {p["id"]: p for p in pool}
    owned = set(selling)
    T = list(range(len(gws)))          # 0..5 period index
    gw_of = {t: gws[t] for t in T}

    prob = pulp.LpProblem("multiweek", pulp.LpMaximize)
    squad = pulp.LpVariable.dicts("sq", (ids, T), cat="Binary")
    tin = pulp.LpVariable.dicts("in", (ids, T), cat="Binary")
    tout = pulp.LpVariable.dicts("out", (ids, T), cat="Binary")
    start = pulp.LpVariable.dicts("st", (ids, T), cat="Binary")
    capt = pulp.LpVariable.dicts("cp", (ids, T), cat="Binary")
    free = pulp.LpVariable.dicts("ft", T, lowBound=0, upBound=MAX_FREE, cat="Integer")
    hits = pulp.LpVariable.dicts("ht", T, lowBound=0, cat="Integer")

    # Objective: starting XI plus the bench's auto-substitution value, less hits.
    prob += (
        pulp.lpSum(
            by[i]["per_gw"].get(gw_of[t], 0.0)
            * (start[i][t] + capt[i][t] + AUTOSUB_WEIGHT * (squad[i][t] - start[i][t]))
            for i in ids
            for t in T
        )
        - HIT_COST * pulp.lpSum(hits[t] for t in T)
    )

    for t in T:
        prob += pulp.lpSum(squad[i][t] for i in ids) == 15
        for pos, n in SQUAD_SHAPE.items():
            prob += pulp.lpSum(squad[i][t] for i in ids if by[i]["pos"] == pos) == n
        for team in {p["team_id"] for p in pool}:
            prob += pulp.lpSum(squad[i][t] for i in ids if by[i]["team_id"] == team) <= TEAM_LIMIT

        prob += pulp.lpSum(start[i][t] for i in ids) == STARTERS
        prob += pulp.lpSum(capt[i][t] for i in ids) == 1
        for pos in SQUAD_SHAPE:
            n = pulp.lpSum(start[i][t] for i in ids if by[i]["pos"] == pos)
            prob += n >= FORMATION_MIN[pos]
            prob += n <= FORMATION_MAX[pos]
        for i in ids:
            prob += start[i][t] <= squad[i][t]
            prob += capt[i][t] <= start[i][t]

        # Squad evolves by transfers. Week 0 starts from the real squad.
        for i in ids:
            previous = squad[i][t - 1] if t > 0 else (1 if i in owned else 0)
            prob += squad[i][t] == previous + tin[i][t] - tout[i][t]
            prob += tin[i][t] + tout[i][t] <= 1

        used = pulp.lpSum(tin[i][t] for i in ids)
        prob += used == pulp.lpSum(tout[i][t] for i in ids)   # size stays at 15

        # Free transfers: one a week, banked up to five, spent before hits.
        if t == 0:
            prob += free[t] <= min(MAX_FREE, squad_row["free_transfers"])
        else:
            prob += free[t] <= free[t - 1] + 1 - pulp.lpSum(tin[i][t - 1] for i in ids)
            prob += free[t] <= MAX_FREE
        prob += hits[t] >= used - free[t]

        # Each player is kept, sold once, or bought once -- never a round trip.
        # FPL permits churn, but you pay the sell-on fee each way and rebuy at
        # market price. With prices held constant the model cannot see that cost,
        # so without this it produces plans that look clever, burn two transfers
        # for a one-week fixture, and lose money doing it.
        for i in ids:
            prob += pulp.lpSum(tout[i][u] for u in range(t + 1)) + tin[i][t] <= 1
            prob += pulp.lpSum(tin[i][u] for u in range(t + 1)) + tout[i][t] <= 1

        # Money. Selling raises what a player is worth; buying costs list price.
        spend = pulp.lpSum(by[i]["cost"] * tin[i][t] for i in ids)
        raise_ = pulp.lpSum(
            (selling.get(i, by[i]["cost"])) * tout[i][t] for i in ids
        )
        prior_spend = pulp.lpSum(
            by[i]["cost"] * tin[i][u] for i in ids for u in range(t)
        )
        prior_raise = pulp.lpSum(
            (selling.get(i, by[i]["cost"])) * tout[i][u] for i in ids for u in range(t)
        )
        prob += spend - raise_ + prior_spend - prior_raise <= squad_row["bank"]

    status = prob.solve(pulp.PULP_CBC_CMD(msg=0, timeLimit=SOLVE_SECONDS))
    if pulp.LpStatus[status] not in ("Optimal",):
        log(f"  solver returned {pulp.LpStatus[status]}")

    plan = []
    for t in T:
        ins = [i for i in ids if tin[i][t].value() and tin[i][t].value() > 0.5]
        outs = [i for i in ids if tout[i][t].value() and tout[i][t].value() > 0.5]
        starters = [i for i in ids if start[i][t].value() and start[i][t].value() > 0.5]
        cap = next((i for i in ids if capt[i][t].value() and capt[i][t].value() > 0.5), None)
        xi = sum(
            by[i]["per_gw"].get(gw_of[t], 0.0) * (2 if i == cap else 1) for i in starters
        )
        plan.append({
            "gw": gw_of[t],
            "in": ins,
            "out": outs,
            "captain": cap,
            "xi_points": round(xi, 3),
            "hits": int(round(hits[t].value() or 0)),
            "free_before": int(round(free[t].value() or 0)),
            "squad": [i for i in ids if squad[i][t].value() and squad[i][t].value() > 0.5],
        })
    return plan, pulp.LpStatus[status], by


def hold_value(pool, gws, selling, by):
    """What the current squad scores if nothing is ever transferred."""
    ids = list(selling)
    prob = pulp.LpProblem("hold", pulp.LpMaximize)
    T = list(range(len(gws)))
    avail = [i for i in ids if i in by]
    st = pulp.LpVariable.dicts("h", (avail, T), cat="Binary")
    cp = pulp.LpVariable.dicts("hc", (avail, T), cat="Binary")
    prob += pulp.lpSum(
        by[i]["per_gw"].get(gws[t], 0.0)
        * (st[i][t] + cp[i][t] + AUTOSUB_WEIGHT * (1 - st[i][t]))
        for i in avail for t in T
    )
    for t in T:
        prob += pulp.lpSum(st[i][t] for i in avail) == STARTERS
        prob += pulp.lpSum(cp[i][t] for i in avail) == 1
        for pos in SQUAD_SHAPE:
            n = pulp.lpSum(st[i][t] for i in avail if by[i]["pos"] == pos)
            prob += n >= FORMATION_MIN[pos]
            prob += n <= FORMATION_MAX[pos]
        for i in avail:
            prob += cp[i][t] <= st[i][t]
    prob.solve(pulp.PULP_CBC_CMD(msg=0, timeLimit=120))
    per_gw = []
    for t in T:
        starters = [i for i in avail if st[i][t].value() and st[i][t].value() > 0.5]
        cap = next((i for i in avail if cp[i][t].value() and cp[i][t].value() > 0.5), None)
        per_gw.append(round(sum(
            by[i]["per_gw"].get(gws[t], 0.0) * (2 if i == cap else 1) for i in starters
        ), 3))
    return per_gw


def main(season: str = CURRENT_SEASON, horizon: int = 6) -> None:
    pool, gws, squad_row, selling = build_pool(season, horizon)
    log(f"  {len(pool)} candidates over gameweeks {gws}, "
        f"bank {squad_row['bank']/10:.1f}m, {squad_row['free_transfers']} free transfer(s)")

    plan, status, by = solve(pool, gws, squad_row, selling)
    hold = hold_value(pool, gws, selling, by)
    log(f"  solver: {status}")

    plan_xi = sum(p["xi_points"] for p in plan)
    plan_hits = sum(p["hits"] for p in plan) * HIT_COST
    hold_xi = sum(hold)

    print(f"\n  {'GW':>4}{'hold':>9}{'plan':>9}{'hits':>6}  transfers")
    print("  " + "-" * 62)
    for i, step in enumerate(plan):
        moves = ", ".join(
            f"{by[o]['name']} -> {by[n]['name']}"
            for o, n in zip(step["out"], step["in"])
        ) or "-"
        print(f"  {step['gw']:>4}{hold[i]:>9.2f}{step['xi_points']:>9.2f}"
              f"{-step['hits'] * HIT_COST if step['hits'] else 0:>6}  {moves}")
    print("  " + "-" * 62)
    print(f"  {'':>4}{hold_xi:>9.2f}{plan_xi:>9.2f}{-plan_hits:>6}")
    net = plan_xi - plan_hits
    print(f"\n  hold the current squad : {hold_xi:.2f}")
    print(f"  transfer plan, net     : {net:.2f}  ({net - hold_xi:+.2f})")
    n_moves = sum(len(p['in']) for p in plan)
    print(f"  {n_moves} transfer(s) across {len(gws)} gameweeks, "
          f"{sum(p['hits'] for p in plan)} of them taking a hit")

    with Run("multiweek", season) as run:
        delete_where("multiweek_plan", f"season=eq.{season}")
        rows = [{
            "season": season,
            "squad_id": squad_row["id"],
            "gw": step["gw"],
            "step": i,
            "xi_points": step["xi_points"],
            "hold_points": hold[i],
            "hits": step["hits"],
            "free_before": step["free_before"],
            "captain": step["captain"],
            "transfers": [
                {"out": by[o]["name"], "out_id": o, "out_team": by[o]["team"],
                 "in": by[n]["name"], "in_id": n, "in_team": by[n]["team"],
                 "gain": round(by[n]["per_gw"].get(step["gw"], 0.0)
                               - by[o]["per_gw"].get(step["gw"], 0.0), 2)}
                for o, n in zip(step["out"], step["in"])
            ],
        } for i, step in enumerate(plan)]
        run.rows = insert_rows("multiweek_plan", rows)


if __name__ == "__main__":
    main(CURRENT_SEASON, int(sys.argv[1]) if len(sys.argv) > 1 else 6)
