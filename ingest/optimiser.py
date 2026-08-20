"""Squad optimisation: the best XI money can buy over the next N gameweeks.

Formulated as a mixed-integer program and solved exactly with CBC, rather than
picked greedily. Greedy selection reliably fails here: the budget, the
three-per-club cap and the formation rules interact, so the best squad is not
the best players chosen one at a time.

Two things the model gets right that a naive "best 15" does not:

  * The objective is the STARTING XI, not the squad. Points sitting on the bench
    do not score, so money spent there is wasted. Left to maximise all 15, the
    model buys four good bench players and a weaker XI.

  * The XI is chosen per gameweek. You can reshuffle your eleven every week
    without a transfer, so a player who blanks in GW2 should be benched that
    week rather than dragging down the squad's value. Modelling one fixed XI
    across the horizon undervalues players with uneven fixtures.

Captaincy is included because it is worth real points -- the captain doubles,
and which player deserves it changes week to week.
"""
from __future__ import annotations

import sys
from collections import defaultdict

import pulp

from common import Run, delete_where, insert_rows, log, select
from config import CURRENT_SEASON
from scoring import DEF, FWD, GK, MID

SQUAD_SHAPE = {GK: 2, DEF: 5, MID: 5, FWD: 3}
FORMATION_MIN = {GK: 1, DEF: 3, MID: 2, FWD: 1}
FORMATION_MAX = {GK: 1, DEF: 5, MID: 5, FWD: 3}
TEAM_LIMIT = 3
BUDGET = 1000          # tenths of a million
STARTERS = 11
HIT_COST = 4
SOLVE_SECONDS = 120

# Bench points are not worthless: when a starter records no minutes, FPL
# substitutes the highest-ranked bench player who did play. Measured on 2025-26,
# a regular starter blanks 14.1% of the time, so in an XI of eleven the bench
# slots are used with probability 0.81, 0.47 and 0.19 -- about 1.48 slots per
# gameweek. Averaged over four bench places that is a 0.37 chance any given
# bench player features.
#
# Without this the optimiser treats the bench as free and buys the cheapest
# legal players, which strengthens the XI by a fraction of a point and throws
# away the cover that actually pays when someone is dropped or injured.
AUTOSUB_WEIGHT = 0.37


def load_players(season: str, horizon: int) -> tuple[list[dict], list[int]]:
    players = select("players", f"season=eq.{season}&select=*")
    teams = select("teams", f"season=eq.{season}&select=id,short_name")
    preds = select("predicted_points", f"season=eq.{season}&select=*")

    gws = sorted({p["gw"] for p in preds})[:horizon]
    points: dict[int, dict[int, float]] = defaultdict(dict)
    for p in preds:
        if p["gw"] in gws:
            points[p["player_id"]][p["gw"]] = float(p["final_score"])

    team_name = {t["id"]: t["short_name"] for t in teams}
    pool = []
    for p in players:
        per_gw = points.get(p["id"])
        if not per_gw:
            continue
        # A player who cannot play is never worth a squad slot.
        if (p.get("status") or "a") in ("u", "n"):
            continue
        total = sum(per_gw.values())
        if total <= 0 or not p.get("now_cost"):
            continue
        pool.append(
            {
                "id": p["id"],
                "name": p["web_name"],
                "team_id": p["team_id"],
                "team": team_name.get(p["team_id"], "?"),
                "pos": p["element_type"],
                "cost": p["now_cost"],
                "status": p.get("status"),
                "news": p.get("news"),
                "ownership": p.get("selected_by_percent"),
                "per_gw": per_gw,
                "total": total,
            }
        )
    return pool, gws


def optimise(
    pool: list[dict],
    gws: list[int],
    budget: int = BUDGET,
    *,
    locked_in: set[int] | None = None,
    available_from: dict[int, int] | None = None,
    max_transfers: int | None = None,
) -> dict | None:
    """Maximise starting-XI points over `gws`.

    `available_from` maps a currently-owned player id to the cash freed by
    selling them; combined with `max_transfers` this turns the problem into
    "what is the best squad I can actually reach", rather than a fantasy.
    """
    prob = pulp.LpProblem("fpl_squad", pulp.LpMaximize)
    ids = [p["id"] for p in pool]
    by_id = {p["id"]: p for p in pool}

    squad = pulp.LpVariable.dicts("squad", ids, cat="Binary")
    start = pulp.LpVariable.dicts("start", (ids, gws), cat="Binary")
    capt = pulp.LpVariable.dicts("capt", (ids, gws), cat="Binary")

    # Objective: starting points with the captain counted twice, plus the
    # expected value of the bench via auto-substitution. `squad - start` is 1
    # exactly when a squad member is benched that week.
    prob += pulp.lpSum(
        by_id[i]["per_gw"].get(gw, 0.0)
        * (start[i][gw] + capt[i][gw] + AUTOSUB_WEIGHT * (squad[i] - start[i][gw]))
        for i in ids
        for gw in gws
    )

    prob += pulp.lpSum(squad[i] for i in ids) == sum(SQUAD_SHAPE.values())
    for pos, n in SQUAD_SHAPE.items():
        prob += pulp.lpSum(squad[i] for i in ids if by_id[i]["pos"] == pos) == n

    for team in {p["team_id"] for p in pool}:
        prob += pulp.lpSum(squad[i] for i in ids if by_id[i]["team_id"] == team) <= TEAM_LIMIT

    # Budget. In reachable mode the money available is the bank plus whatever
    # the players actually sold would raise.
    if available_from is not None:
        owned = set(available_from)
        prob += (
            pulp.lpSum(by_id[i]["cost"] * squad[i] for i in ids if i not in owned)
            <= budget
            + pulp.lpSum(
                available_from[i] * (1 - squad[i]) for i in ids if i in owned
            )
        )
        if max_transfers is not None:
            # Transfers made = owned players no longer in the squad.
            prob += (
                pulp.lpSum(1 - squad[i] for i in ids if i in owned) <= max_transfers
            )
        for i in owned:
            if i not in by_id:
                continue
    else:
        prob += pulp.lpSum(by_id[i]["cost"] * squad[i] for i in ids) <= budget

    for i in (locked_in or set()):
        if i in squad:
            prob += squad[i] == 1

    for gw in gws:
        prob += pulp.lpSum(start[i][gw] for i in ids) == STARTERS
        prob += pulp.lpSum(capt[i][gw] for i in ids) == 1
        for pos in SQUAD_SHAPE:
            n = pulp.lpSum(start[i][gw] for i in ids if by_id[i]["pos"] == pos)
            prob += n >= FORMATION_MIN[pos]
            prob += n <= FORMATION_MAX[pos]
        for i in ids:
            prob += start[i][gw] <= squad[i]
            prob += capt[i][gw] <= start[i][gw]

    status = prob.solve(pulp.PULP_CBC_CMD(msg=0, timeLimit=SOLVE_SECONDS))
    if pulp.LpStatus[status] not in ("Optimal",):
        log(f"  solver returned {pulp.LpStatus[status]}")
        return None

    chosen = [by_id[i] for i in ids if squad[i].value() and squad[i].value() > 0.5]
    per_gw_roles = {
        gw: {
            "starters": [i for i in ids if start[i][gw].value() and start[i][gw].value() > 0.5],
            "captain": next((i for i in ids if capt[i][gw].value() and capt[i][gw].value() > 0.5), None),
        }
        for gw in gws
    }
    xi_points = sum(
        by_id[i]["per_gw"].get(gw, 0.0)
        * (1 + (1 if per_gw_roles[gw]["captain"] == i else 0))
        for gw in gws
        for i in per_gw_roles[gw]["starters"]
    )
    return {
        "squad": chosen,
        "roles": per_gw_roles,
        "xi_points": round(xi_points, 3),
        "squad_cost": sum(p["cost"] for p in chosen),
        "status": pulp.LpStatus[status],
    }


def describe(result: dict, gws: list[int], label: str) -> None:
    by_id = {p["id"]: p for p in result["squad"]}
    names = {GK: "GKP", DEF: "DEF", MID: "MID", FWD: "FWD"}
    log(f"\n  {label}: {result['xi_points']:.1f} XI points, "
        f"cost {result['squad_cost']/10:.1f}m")
    header = f"    {'Player':<16}{'Tm':<5}{'Pos':<5}{'£':>6}"
    for gw in gws:
        header += f"{'GW'+str(gw):>8}"
    header += f"{'3GW':>8}"
    print(header)
    order = sorted(result["squad"], key=lambda p: (p["pos"], -p["total"]))
    for p in order:
        line = f"    {p['name'][:15]:<16}{p['team']:<5}{names[p['pos']]:<5}{p['cost']/10:>6.1f}"
        for gw in gws:
            starting = p["id"] in result["roles"][gw]["starters"]
            cap = result["roles"][gw]["captain"] == p["id"]
            v = p["per_gw"].get(gw, 0.0)
            mark = "C" if cap else ("" if starting else "b")
            line += f"{v:>7.2f}{mark:<1}"
        line += f"{p['total']:>8.2f}"
        print(line)


def current_squad(season: str) -> tuple[dict, dict[int, int]] | tuple[None, None]:
    """The live squad and what each player would raise if sold."""
    rows = select("my_squad", f"season=eq.{season}&is_current=is.true&select=*")
    if not rows:
        return None, None
    squad = rows[0]
    picks = select("my_squad_picks", f"squad_id=eq.{squad['id']}&select=*")
    return squad, {p["player_id"]: p["selling_price"] for p in picks}


def score_existing(pool: list[dict], gws: list[int], owned: set[int]) -> float:
    """The current squad's own XI points, on the same basis as the optimiser.

    Scored with per-gameweek starters and a captain, so it is directly
    comparable -- otherwise the optimiser looks better than it is, purely
    because it counts captaincy and the naive comparison does not.
    """
    subset = [p for p in pool if p["id"] in owned]
    if len(subset) < 11:
        return 0.0
    total = 0.0
    names = {p["id"]: p for p in subset}
    for gw in gws:
        by_pos: dict[int, list] = defaultdict(list)
        for p in subset:
            by_pos[p["pos"]].append(p)
        for lst in by_pos.values():
            lst.sort(key=lambda x: x["per_gw"].get(gw, 0.0), reverse=True)
        best = -1.0
        for n_def in range(FORMATION_MIN[DEF], FORMATION_MAX[DEF] + 1):
            for n_mid in range(FORMATION_MIN[MID], FORMATION_MAX[MID] + 1):
                for n_fwd in range(FORMATION_MIN[FWD], FORMATION_MAX[FWD] + 1):
                    if 1 + n_def + n_mid + n_fwd != STARTERS:
                        continue
                    counts = {GK: 1, DEF: n_def, MID: n_mid, FWD: n_fwd}
                    if any(len(by_pos.get(k, [])) < v for k, v in counts.items()):
                        continue
                    xi = [p for k, v in counts.items() for p in by_pos[k][:v]]
                    pts = [p["per_gw"].get(gw, 0.0) for p in xi]
                    best = max(best, sum(pts) + max(pts))  # captain doubles
        total += max(0.0, best)
    return round(total, 3)


def main() -> None:
    season = CURRENT_SEASON
    horizon = 6
    with Run("optimiser", season) as run:
        pool, gws = load_players(season, horizon)
        log(f"  {len(pool)} selectable players, gameweeks {gws}")

        dream = optimise(pool, gws)
        if not dream:
            raise RuntimeError("no optimal squad found within the time limit")
        describe(dream, gws, "Best possible squad from a clean 100.0m")

        rows = [
            {
                "season": season,
                "gw": gws[0],
                "mode": "dream",
                "squad_id": None,
                "transfers_allowed": None,
                "budget": BUDGET,
                "xi_points": dream["xi_points"],
                "squad_cost": dream["squad_cost"],
                "hit_cost": 0,
                "net_points": dream["xi_points"],
                "detail": {
                    "gameweeks": gws,
                    "squad": [
                        {
                            "player_id": p["id"],
                            "name": p["name"],
                            "team": p["team"],
                            "pos": p["pos"],
                            "cost": p["cost"],
                            "per_gw": {str(g): round(p["per_gw"].get(g, 0.0), 2) for g in gws},
                            "total": round(p["total"], 2),
                        }
                        for p in dream["squad"]
                    ],
                    "roles": {str(g): dream["roles"][g] for g in gws},
                },
            }
        ]
        # Reachable: the best squad actually attainable from the current one.
        squad_row, selling = current_squad(season)
        if squad_row and selling:
            owned = set(selling)
            # An owned player filtered out of the pool cannot be represented as
            # "kept", which would silently force a transfer that is not needed.
            in_pool = {p["id"] for p in pool}
            missing = owned - in_pool
            if missing:
                log(f"  {len(missing)} owned player(s) have no usable projection; "
                    "they will be treated as sellable only")
            baseline = score_existing(pool, gws, owned)
            free_transfers = squad_row["free_transfers"]
            log(f"\n  current squad scores {baseline:.1f} XI points "
                f"(bank {squad_row['bank']/10:.1f}m, {free_transfers} free transfer(s))")
            log(f"  {'transfers':>10}{'XI points':>12}{'gain':>9}{'hit':>6}{'net gain':>11}")
            best_net, best_n = 0.0, 0
            for n in range(0, 6):
                res = optimise(
                    pool, gws,
                    budget=squad_row["bank"],
                    available_from=selling,
                    max_transfers=n,
                )
                if not res:
                    continue
                gain = res["xi_points"] - baseline
                hit = HIT_COST * max(0, n - free_transfers)
                net = gain - hit
                log(f"  {n:>10}{res['xi_points']:>12.1f}{gain:>+9.1f}{-hit:>6}{net:>+11.1f}")
                if net > best_net:
                    best_net, best_n = net, n
                rows.append({
                    "season": season, "gw": gws[0], "mode": "reachable",
                    "squad_id": squad_row["id"],
                    "transfers_allowed": n, "budget": squad_row["bank"],
                    "xi_points": res["xi_points"], "squad_cost": res["squad_cost"],
                    "hit_cost": hit, "net_points": round(net, 3),
                    "detail": {
                        "gameweeks": gws,
                        "baseline_xi_points": baseline,
                        "free_transfers": free_transfers,
                        "squad": [
                            {"player_id": p["id"], "name": p["name"], "team": p["team"],
                             "pos": p["pos"], "cost": p["cost"],
                             "owned": p["id"] in owned,
                             "per_gw": {str(g): round(p["per_gw"].get(g, 0.0), 2) for g in gws},
                             "total": round(p["total"], 2)}
                            for p in res["squad"]
                        ],
                        "out": [
                            {"player_id": i} for i in owned
                            if i not in {p["id"] for p in res["squad"]}
                        ],
                        "roles": {str(g): res["roles"][g] for g in gws},
                    },
                })
            log(f"\n  best move: {best_n} transfer(s) for a net {best_net:+.1f} points")
        else:
            log("\n  no current squad imported; skipping the reachable build")

        delete_where("optimal_squads", f"season=eq.{season}&gw=eq.{gws[0]}")
        run.rows = insert_rows("optimal_squads", rows)
        log(f"  stored {run.rows} optimal squad(s)")


if __name__ == "__main__":
    main()
