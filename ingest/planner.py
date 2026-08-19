"""Squad scoring and the transfer planner.

Recommendations only. Nothing here executes a transfer -- the brief is explicit
that this is not an autopilot, and there is no write path to FPL anywhere in the
project.

Transfer economy, confirmed against the live game settings rather than assumed:
one free transfer a week, up to five bankable (`max_extra_free_transfers = 4`),
and -4 points for each transfer beyond the free ones.
"""
from __future__ import annotations

import sys
from collections import defaultdict
from itertools import product

from common import Run, delete_where, insert_rows, log, select
from config import CURRENT_SEASON
from scoring import DEF, FWD, GK, MID

HIT_COST = 4
MAX_FREE_TRANSFERS = 5
SQUAD_TEAM_LIMIT = 3
# FPL formation rules: exactly 1 keeper, then within these bounds, 11 in total.
FORMATION_BOUNDS = {GK: (1, 1), DEF: (3, 5), MID: (2, 5), FWD: (1, 3)}
# "Same price bracket" for the weak-pick comparison, in tenths of a million.
PRICE_BRACKET = 5
# Only suggest a swap that clears this many points over three gameweeks, before
# any hit. Below it the projection is not precise enough to justify a move.
MIN_GROSS_GAIN = 0.5


def best_xi(squad: list[dict]) -> tuple[list[dict], list[dict]]:
    """Highest-scoring legal XI, and the four on the bench.

    Enumerates every legal formation rather than picking greedily by score: a
    greedy XI can end up illegal, and there are only a handful of shapes.
    """
    by_pos: dict[int, list[dict]] = defaultdict(list)
    for p in squad:
        by_pos[p["element_type"]].append(p)
    for players in by_pos.values():
        players.sort(key=lambda p: p["points_3gw"], reverse=True)

    best_total, best_shape = -1.0, None
    for n_def, n_mid, n_fwd in product(range(3, 6), range(2, 6), range(1, 4)):
        if 1 + n_def + n_mid + n_fwd != 11:
            continue
        counts = {GK: 1, DEF: n_def, MID: n_mid, FWD: n_fwd}
        if any(len(by_pos.get(pos, [])) < n for pos, n in counts.items()):
            continue
        total = sum(
            sum(p["points_3gw"] for p in by_pos[pos][:n]) for pos, n in counts.items()
        )
        if total > best_total:
            best_total, best_shape = total, counts

    if not best_shape:
        return sorted(squad, key=lambda p: p["points_3gw"], reverse=True)[:11], []

    starters = [p for pos, n in best_shape.items() for p in by_pos[pos][:n]]
    starter_ids = {p["player_id"] for p in starters}
    bench = [p for p in squad if p["player_id"] not in starter_ids]
    bench.sort(key=lambda p: p["points_3gw"], reverse=True)
    return starters, bench


def bracket_percentile(player: dict, universe: list[dict]) -> float | None:
    """Where this player ranks among same-position players at a similar price."""
    peers = [
        p
        for p in universe
        if p["element_type"] == player["element_type"]
        and abs(p["now_cost"] - player["now_cost"]) <= PRICE_BRACKET
        and p["player_id"] != player["player_id"]
    ]
    if len(peers) < 4:
        return None
    worse = sum(1 for p in peers if p["points_3gw"] < player["points_3gw"])
    return round(worse / len(peers), 3)


def load_context(season: str, horizon: int = 3):
    squad_rows = select("my_squad", f"season=eq.{season}&is_current=is.true&select=*")
    if not squad_rows:
        raise RuntimeError(
            "no current squad -- import one first (ingest/squad.py, or the Squad page)"
        )
    squad = squad_rows[0]
    picks = select("my_squad_picks", f"squad_id=eq.{squad['id']}&select=*")
    players = select("players", f"season=eq.{season}&select=*")
    teams = select("teams", f"season=eq.{season}&select=id,short_name")
    predictions = select("predicted_points", f"season=eq.{season}&select=*")

    gws = sorted({p["gw"] for p in predictions})[:horizon]
    points: dict[int, dict[int, float]] = defaultdict(dict)
    for p in predictions:
        if p["gw"] in gws:
            points[p["player_id"]][p["gw"]] = float(p["final_score"])

    team_name = {t["id"]: t["short_name"] for t in teams}
    universe = []
    for p in players:
        per_gw = points.get(p["id"], {})
        universe.append(
            {
                "player_id": p["id"],
                "web_name": p["web_name"],
                "element_type": p["element_type"],
                "team_id": p["team_id"],
                "team": team_name.get(p["team_id"], "?"),
                "now_cost": p["now_cost"] or 0,
                "status": p.get("status"),
                "news": p.get("news"),
                "selected_by_percent": p.get("selected_by_percent"),
                "points_next": per_gw.get(gws[0], 0.0) if gws else 0.0,
                "points_3gw": sum(per_gw.values()),
                "per_gw": per_gw,
            }
        )
    return squad, picks, universe, gws


def build_squad_view(picks: list[dict], universe: list[dict]) -> list[dict]:
    by_id = {p["player_id"]: p for p in universe}
    out = []
    for pick in picks:
        base = by_id.get(pick["player_id"])
        if not base:
            continue
        row = dict(base)
        row["selling_price"] = pick["selling_price"]
        row["purchase_price"] = pick["purchase_price"]
        row["is_captain"] = pick["is_captain"]
        row["is_vice_captain"] = pick["is_vice_captain"]
        out.append(row)
    return out


def candidates_for(
    out_player: dict,
    universe: list[dict],
    squad: list[dict],
    bank: int,
) -> list[dict]:
    """Affordable, legal replacements for one player."""
    budget = out_player["selling_price"] + bank
    squad_ids = {p["player_id"] for p in squad}

    # Club counts after removing the outgoing player -- a swap must not breach
    # the three-per-club limit, which is easy to forget and invalidates a team.
    club_counts: dict[int, int] = defaultdict(int)
    for p in squad:
        if p["player_id"] != out_player["player_id"]:
            club_counts[p["team_id"]] += 1

    results = []
    for cand in universe:
        if cand["player_id"] in squad_ids:
            continue
        if cand["element_type"] != out_player["element_type"]:
            continue
        if cand["now_cost"] > budget:
            continue
        if club_counts[cand["team_id"]] >= SQUAD_TEAM_LIMIT:
            continue
        # An unavailable player is never an upgrade.
        if (cand.get("status") or "a") in ("u", "n"):
            continue
        gain = cand["points_3gw"] - out_player["points_3gw"]
        if gain < MIN_GROSS_GAIN:
            continue
        results.append({"candidate": cand, "gross_gain": gain})
    results.sort(key=lambda r: r["gross_gain"], reverse=True)
    return results


def plan(season: str = CURRENT_SEASON, horizon: int = 3, top_n: int = 25) -> list[dict]:
    """Ranked single-transfer options, plus a coherent multi-transfer plan.

    Two separate questions, kept separate on purpose:

      Each row answers "if I made ONLY this transfer, what do I gain?" -- so its
      hit is simply whether a free transfer is available. Ranking rows and then
      charging a cumulative hit down the list would be nonsense, because the
      options conflict: three different swaps all bringing in the same striker
      cannot be taken together, and pretending otherwise prices a transfer you
      could never make.

      The plan is the coherent version: a greedy sequence of non-conflicting
      swaps, tracking the bank as it goes and charging -4 once the free
      transfers run out. That is the thing you can actually execute.
    """
    squad_row, picks, universe, gws = load_context(season, horizon)
    squad = build_squad_view(picks, universe)
    if len(squad) != 15:
        log(f"  warning: squad has {len(squad)} players with predictions, expected 15")

    bank = squad_row["bank"]
    free_transfers = min(squad_row["free_transfers"], MAX_FREE_TRANSFERS)
    starters, bench = best_xi(squad)
    starter_ids = {p["player_id"] for p in starters}

    log(
        f"  squad value {sum(p['selling_price'] for p in squad) / 10:.1f} + bank "
        f"{bank / 10:.1f}, {free_transfers} free transfer(s)"
    )
    log(f"  best XI projects {sum(p['points_3gw'] for p in starters):.1f} over {len(gws)} GWs")

    raw: list[dict] = []
    for player in squad:
        for option in candidates_for(player, universe, squad, bank)[:6]:
            cand = option["candidate"]
            starter = player["player_id"] in starter_ids
            raw.append(
                {
                    "out": player,
                    "in": cand,
                    "gross": option["gross_gain"],
                    "starter": starter,
                    # Improving a bench player only pays out when someone ahead
                    # of them does not play, so it is worth less than it looks.
                    "priority": option["gross_gain"] + (1.5 if starter else 0.0),
                }
            )
    raw.sort(key=lambda r: r["priority"], reverse=True)

    # One row per incoming player, keeping their best partner, so the list is a
    # set of genuine alternatives rather than the same signing five times.
    best_by_in: dict[int, dict] = {}
    for r in raw:
        key = r["in"]["player_id"]
        if key not in best_by_in or r["priority"] > best_by_in[key]["priority"]:
            best_by_in[key] = r
    options = sorted(best_by_in.values(), key=lambda r: r["priority"], reverse=True)[:top_n]

    # The executable plan: greedy, non-conflicting, bank-aware.
    plan_bank = bank
    used_out: set[int] = set()
    used_in: set[int] = set()
    plan_steps: dict[int, dict] = {}
    for r in options:
        out_id, in_id = r["out"]["player_id"], r["in"]["player_id"]
        if out_id in used_out or in_id in used_in:
            continue
        cash = r["out"]["selling_price"] - r["in"]["now_cost"]
        if plan_bank + cash < 0:
            continue
        step = len(plan_steps) + 1
        marginal_hit = HIT_COST * (0 if step <= free_transfers else 1)
        plan_steps[in_id] = {
            "step": step,
            "marginal_hit": marginal_hit,
            "net_after_hit": round(r["gross"] - marginal_hit, 3),
            "bank_after": plan_bank + cash,
            "gross": round(r["gross"], 3),
        }
        plan_bank += cash
        used_out.add(out_id)
        used_in.add(in_id)

    # How deep to go is the actual decision: each extra transfer past the free
    # ones costs 4 points, so the best plan is the depth whose CUMULATIVE net is
    # highest -- often one transfer, not the longest sequence available.
    ordered = sorted(plan_steps.values(), key=lambda x: x["step"])
    running = 0.0
    best_depth, best_cumulative = 0, 0.0
    for stepinfo in ordered:
        running += stepinfo["net_after_hit"]
        stepinfo["cumulative_net"] = round(running, 3)
        if running > best_cumulative:
            best_depth, best_cumulative = stepinfo["step"], running
    for stepinfo in ordered:
        stepinfo["recommended_depth"] = best_depth
        stepinfo["in_recommended_plan"] = stepinfo["step"] <= best_depth
    if ordered:
        log(
            f"  recommended: {best_depth} transfer(s) for a net "
            f"{best_cumulative:+.2f} over {len(gws)} GWs "
            f"(taking all {len(ordered)} would net "
            f"{ordered[-1]['cumulative_net']:+.2f})"
        )

    rows = []
    for rank, r in enumerate(options, start=1):
        out_p, in_p = r["out"], r["in"]
        # This row on its own: one transfer, free if one is available.
        single_hit = 0 if free_transfers >= 1 else HIT_COST
        step = plan_steps.get(in_p["player_id"])
        rows.append(
            {
                "season": season,
                "gw": gws[0] if gws else 0,
                "squad_id": squad_row["id"],
                "player_out": out_p["player_id"],
                "player_in": in_p["player_id"],
                "out_cost": out_p["selling_price"],
                "in_cost": in_p["now_cost"],
                "cash_delta": out_p["selling_price"] - in_p["now_cost"],
                "transfers_used": 1,
                "hit_cost": single_hit,
                "gross_gain_3gw": round(r["gross"], 3),
                "net_gain_3gw": round(r["gross"] - single_hit, 3),
                "rank": rank,
                "reasoning": {
                    "out": {
                        "name": out_p["web_name"],
                        "team": out_p["team"],
                        "price": out_p["selling_price"] / 10,
                        "points_3gw": round(out_p["points_3gw"], 2),
                        "points_next": round(out_p["points_next"], 2),
                        "in_best_xi": r["starter"],
                        "status": out_p.get("status"),
                        "news": out_p.get("news"),
                        "price_bracket_percentile": bracket_percentile(out_p, universe),
                    },
                    "in": {
                        "name": in_p["web_name"],
                        "team": in_p["team"],
                        "price": in_p["now_cost"] / 10,
                        "points_3gw": round(in_p["points_3gw"], 2),
                        "points_next": round(in_p["points_next"], 2),
                        "ownership": in_p.get("selected_by_percent"),
                        "price_bracket_percentile": bracket_percentile(in_p, universe),
                    },
                    "per_gameweek": {
                        str(gw): {
                            "out": round(out_p["per_gw"].get(gw, 0.0), 2),
                            "in": round(in_p["per_gw"].get(gw, 0.0), 2),
                        }
                        for gw in gws
                    },
                    "economy": {
                        "free_transfers_available": free_transfers,
                        "hit_if_taken_alone": single_hit,
                        "basis": "one transfer, in isolation",
                    },
                    # Present only for swaps that fit the executable sequence.
                    "plan": step,
                    "trend_note": "Trend adjustments are zero; the engine failed its backtest.",
                },
            }
        )
    return rows


def squad_report(season: str = CURRENT_SEASON, horizon: int = 3) -> None:
    """Console view of the squad, for checking without the UI."""
    squad_row, picks, universe, gws = load_context(season, horizon)
    squad = build_squad_view(picks, universe)
    starters, bench = best_xi(squad)
    names = {GK: "GKP", DEF: "DEF", MID: "MID", FWD: "FWD"}

    print(f"\n{'':<3}{'Player':<16}{'Tm':<5}{'Pos':<5}{'£':>6}{'Next':>7}{'3GW':>7}{'Pctile':>8}")
    print("-" * 57)
    for label, group in (("XI", starters), ("SUB", bench)):
        for p in sorted(group, key=lambda x: x["points_3gw"], reverse=True):
            pc = bracket_percentile(p, universe)
            print(
                f"{label:<3}{p['web_name'][:15]:<16}{p['team']:<5}"
                f"{names[p['element_type']]:<5}{p['selling_price'] / 10:>6.1f}"
                f"{p['points_next']:>7.2f}{p['points_3gw']:>7.2f}"
                f"{(f'{pc:.0%}' if pc is not None else '-'):>8}"
            )
    print(
        f"\nBest XI over GW{gws[0]}-{gws[-1]}: "
        f"{sum(p['points_3gw'] for p in starters):.1f} points"
    )


def main() -> None:
    season = CURRENT_SEASON
    if "--report" in sys.argv:
        squad_report(season)
        return
    with Run("planner", season) as run:
        rows = plan(season)
        # Suggestions are only meaningful as a complete ranked set for one
        # gameweek; leaving last run's behind would mix two rankings.
        gw = rows[0]["gw"] if rows else 0
        delete_where("transfer_suggestions", f"season=eq.{season}&gw=eq.{gw}")
        run.rows = insert_rows("transfer_suggestions", rows)
        log(f"  {len(rows)} transfer suggestions for GW{gw}")
        for r in rows[:5]:
            rr = r["reasoning"]
            log(
                f"    {rr['out']['name']} -> {rr['in']['name']}  "
                f"gross {r['gross_gain_3gw']:+.2f}  hit {-r['hit_cost']}  "
                f"net {r['net_gain_3gw']:+.2f}"
            )


if __name__ == "__main__":
    main()
