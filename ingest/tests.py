"""Unit checks for the pure logic, no network and no database.

Covers the rules that would be expensive to get wrong and silent when they are:
FPL's selling-price formula, squad legality, formation legality, the shrinkage
estimator's behaviour at the extremes, and the goals-conceded deduction.
"""
from __future__ import annotations

import sys

failures: list[str] = []


def check(name: str, got, want, tol: float | None = None) -> None:
    ok = abs(got - want) <= tol if tol is not None else got == want
    if not ok:
        failures.append(f"{name}: got {got!r}, wanted {want!r}")
    print(f"  {'ok  ' if ok else 'FAIL'} {name}")


def main() -> int:
    from common import dedupe
    from config import season_weight
    from depth import build_depth_priors
    from planner import best_xi
    from scoring import (
        elo_multiplier,
        expected_concede_penalty,
        poisson_zero,
    )
    from shots import zone_of
    from squad import selling_price, validate
    from trends import estimate_shrinkage

    print("selling price (FPL returns half of any rise, rounded down to 0.1m)")
    check("no change", selling_price(100, 100), 100)
    check("1.0m rise gives 0.5m back", selling_price(100, 110), 105)
    check("0.5m rise rounds down", selling_price(100, 105), 102)
    check("a fall sells at current price", selling_price(100, 90), 90)
    check("unknown purchase falls back", selling_price(None, 75), 75)

    print("\ndedupe on the conflict key")
    rows = [{"a": 1, "v": "old"}, {"a": 1, "v": "new"}, {"a": 2, "v": "keep"}]
    out = dedupe(rows, "a")
    check("collapses duplicates", len(out), 2)
    check("last occurrence wins", out[0]["v"], "new")

    print("\nseason weighting")
    check("current season is undiscounted", season_weight("2026-27", "2026-27"), 1.0)
    check("last season", season_weight("2025-26", "2026-27"), 0.55, tol=1e-9)
    check("three back decays further", season_weight("2023-24", "2026-27"), 0.55**3, tol=1e-9)

    print("\nsquad legality")
    players = {}
    picks = []
    pid = 0
    for pos, n in ((1, 2), (2, 5), (3, 5), (4, 3)):
        for _ in range(n):
            pid += 1
            players[pid] = {"element_type": pos, "team_id": pid % 8, "now_cost": 50}
            picks.append({"player_id": pid, "selling_price": 50})
    check("a legal squad has no problems", validate(picks, players, 250), [])

    bad = [dict(p) for p in picks]
    for p in bad[:4]:
        players[p["player_id"]]["team_id"] = 99
    problems = validate(bad, players, 250)
    check("four from one club is rejected", any("more than 3" in p for p in problems), True)

    over = [dict(p, selling_price=100) for p in picks]
    problems = validate(over, players, 100)
    check("over budget is rejected", any("budget" in p for p in problems), True)

    print("\nbest XI is a legal formation")
    squad = []
    for pos, n in ((1, 2), (2, 5), (3, 5), (4, 3)):
        for i in range(n):
            squad.append(
                {"player_id": len(squad) + 1, "element_type": pos, "points_3gw": float(10 - i)}
            )
    starters, bench = best_xi(squad)
    counts = {pos: sum(1 for p in starters if p["element_type"] == pos) for pos in (1, 2, 3, 4)}
    check("eleven starters", len(starters), 11)
    check("four on the bench", len(bench), 4)
    check("exactly one keeper", counts[1], 1)
    check("at least three defenders", counts[2] >= 3, True)
    check("at least two midfielders", counts[3] >= 2, True)
    check("at least one forward", counts[4] >= 1, True)

    print("\nshrinkage estimator")
    # Every team identical apart from sampling noise -> shrink hard.
    identical = {t: (10.0, 100.0) for t in range(20)}
    k_noise, _ = estimate_shrinkage(identical, 0.1, {t: [0.1] * 100 for t in identical})
    check("no real spread shrinks to the ceiling", k_noise >= 400, True)
    # Wide, genuine spread -> shrink far less.
    spread = {t: (float(t) * 5, 100.0) for t in range(20)}
    values = {t: [1.0] * int(t * 5) + [0.0] * (100 - int(t * 5)) for t in range(20)}
    k_real, between = estimate_shrinkage(spread, 0.475, values)
    check("real spread shrinks less", k_real < k_noise, True)
    check("between-team spread is positive", between > 0, True)

    print("\nfixture and scoring maths")
    check("average opponent is neutral", elo_multiplier(1800, 1750), 1.0, tol=1e-9)
    check("weak opponent helps", elo_multiplier(1800, 1500) > 1.0, True)
    check("strong opponent hurts", elo_multiplier(1800, 2050) < 1.0, True)
    check("clean sheet at lambda 0 is certain", poisson_zero(0.0), 1.0, tol=1e-9)
    check("clean sheet falls as lambda rises", poisson_zero(2.0) < poisson_zero(1.0), True)
    # -1 per TWO conceded: one goal costs nothing, so the deduction is not linear.
    check("deduction floors at even goals", expected_concede_penalty(0.0), 0.0, tol=1e-9)
    check("some deduction once goals are likely", expected_concede_penalty(2.0) < -0.3, True)

    print("\nshot zones")
    check("close and central", zone_of(3, 50), "six_yard_central")
    check("penalty area, attacking left", zone_of(12, 70), "penalty_area_left")
    check("distance shot from the right", zone_of(30, 20), "outside_box_right")
    check("missing coordinates", zone_of(None, None), "unknown")

    print("\ndepth chart")
    squad_players = [
        {"id": 1, "team_id": 1, "element_type": 1, "now_cost": 55, "selected_by_percent": 1, "minutes": 3000},
        {"id": 2, "team_id": 1, "element_type": 1, "now_cost": 45, "selected_by_percent": 20, "minutes": 0},
    ]
    priors = build_depth_priors(squad_players)
    check("dearer keeper is first choice", priors[1]["depth_rank"], 0)
    check("first choice expected to start", priors[1]["p60"] > 0.8, True)
    check("backup rarely starts", priors[2]["p60"] < 0.1, True)

    print("\noptimiser respects the rules")
    from optimiser import SQUAD_SHAPE, TEAM_LIMIT, optimise

    # A synthetic league: cheap players everywhere, plus one expensive star per
    # club, so the budget and the three-per-club cap both actually bind.
    pool, pid = [], 0
    for team in range(6):
        for pos, n in ((1, 3), (2, 8), (3, 8), (4, 5)):
            for i in range(n):
                pid += 1
                star = i == 0
                pool.append({
                    "id": pid, "name": f"p{pid}", "team_id": team, "team": f"T{team}",
                    "pos": pos, "cost": 120 if star else 40,
                    "per_gw": {1: 9.0 if star else 1.0, 2: 9.0 if star else 1.0},
                    "total": 18.0 if star else 2.0,
                })
    res = optimise(pool, [1, 2], budget=1000)
    check("solver finds an optimum", res is not None, True)
    if res:
        squad = res["squad"]
        check("fifteen players", len(squad), 15)
        for pos, want in SQUAD_SHAPE.items():
            check(f"position {pos} count", sum(1 for p in squad if p["pos"] == pos), want)
        from collections import Counter
        per_club = Counter(p["team_id"] for p in squad)
        check("three-per-club respected", max(per_club.values()) <= TEAM_LIMIT, True)
        check("inside budget", res["squad_cost"] <= 1000, True)
        for gw in (1, 2):
            starters = res["roles"][gw]["starters"]
            by_pos = Counter(next(p["pos"] for p in squad if p["id"] == i) for i in starters)
            check(f"GW{gw}: eleven starters", len(starters), 11)
            check(f"GW{gw}: one keeper", by_pos[1], 1)
            check(f"GW{gw}: 3-5 defenders", 3 <= by_pos[2] <= 5, True)
            check(f"GW{gw}: captain is a starter",
                  res["roles"][gw]["captain"] in starters, True)
        # Bench points do not score, so the optimiser must not spend on the bench.
        starters_gw1 = set(res["roles"][1]["starters"])
        bench_cost = sum(p["cost"] for p in squad if p["id"] not in starters_gw1)
        xi_cost = sum(p["cost"] for p in squad if p["id"] in starters_gw1)
        check("bench is cheaper than the XI", bench_cost < xi_cost, True)

    print()
    if failures:
        print(f"{len(failures)} failure(s):")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
