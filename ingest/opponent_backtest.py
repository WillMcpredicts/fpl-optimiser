"""Validate the opponent-generosity adjustment, and record the result.

Answers the only question that matters for a feature like this: does it improve
predictions on data it has never seen, OVER AND ABOVE the fixture adjustment the
model already applies?

The incremental part is essential. A strong team both concedes few points and
carries a high Elo, so testing the position factor against a bare player rate
mostly re-discovers fixture difficulty and flatters the result. Here the Elo
adjustment is applied first, and the position factor has to earn what is left.

Protocol: tune damping on GW10-24 of a completed season, score GW25-38 without
touching the tuning again.

Run:  python ingest/opponent_backtest.py [season]
"""
from __future__ import annotations

import math
import statistics
import sys
from collections import defaultdict

from common import Run, delete_where, insert_rows, log, select
from opponent_strength import ELIGIBLE
from scoring import ELO_K, ELO_REFERENCE, clamp

POS_NAMES = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}
START_GW, SPLIT_GW = 10, 25
MIN_PLAYER_90S, MIN_OPPONENT_90S = 3.0, 20.0
DAMPING_GRID = [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]


def elo_by_team(season: str) -> dict[int, float]:
    rows = select("team_match_stats", f"season=eq.{season}&select=team_id,elo")
    grouped: dict[int, list[float]] = defaultdict(list)
    for r in rows:
        if r.get("elo"):
            grouped[r["team_id"]].append(float(r["elo"]))
    return {k: statistics.mean(v) for k, v in grouped.items()}


def build_samples(season: str) -> list[dict]:
    players = {
        p["id"]: p["element_type"]
        for p in select("players", f"season=eq.{season}&select=id,element_type")
    }
    elo = elo_by_team(season)
    rows = [
        r
        for r in select("player_gameweeks", f"season=eq.{season}&select=*")
        if (r.get("minutes") or 0) > 0 and r.get("opponent_team") and players.get(r["player_id"])
    ]
    by_gw: dict[int, list[dict]] = defaultdict(list)
    for r in rows:
        r["pos"] = players[r["player_id"]]
        by_gw[r["gw"]].append(r)

    def difficulty(opponent: int) -> float:
        e = elo.get(opponent)
        if not e:
            return 1.0
        return clamp(math.exp(ELO_K * (ELO_REFERENCE - e) / 400.0), 0.55, 1.8)

    samples = []
    for gw in range(START_GW, max(by_gw) + 1):
        prior = [r for g in range(1, gw) for r in by_gw[g]]
        pmin, ppts = defaultdict(float), defaultdict(float)
        omin, opts = defaultdict(float), defaultdict(float)
        lmin, lpts = defaultdict(float), defaultdict(float)
        for r in prior:
            pid, pos, opp, m = r["player_id"], r["pos"], r["opponent_team"], r["minutes"]
            pts = r.get("total_points") or 0
            pmin[pid] += m
            ppts[pid] += pts
            omin[(opp, pos)] += m
            opts[(opp, pos)] += pts
            lmin[pos] += m
            lpts[pos] += pts
        for r in by_gw[gw]:
            pid, pos, opp, m = r["player_id"], r["pos"], r["opponent_team"], r["minutes"]
            if pmin[pid] / 90.0 < MIN_PLAYER_90S:
                continue
            if omin[(opp, pos)] / 90.0 < MIN_OPPONENT_90S:
                continue
            league = lpts[pos] / (lmin[pos] / 90.0) if lmin[pos] else 0.0
            if league <= 0:
                continue
            samples.append(
                {
                    "gw": gw,
                    "pos": pos,
                    "actual": r.get("total_points") or 0,
                    "rate": ppts[pid] / (pmin[pid] / 90.0) * (m / 90.0),
                    "elo": difficulty(opp),
                    "factor": (opts[(opp, pos)] / (omin[(opp, pos)] / 90.0)) / league,
                }
            )
    return samples


def mae(samples: list[dict], predict) -> float:
    return statistics.mean(abs(s["actual"] - predict(s)) for s in samples)


def main(season: str = "2025-26") -> None:
    samples = build_samples(season)
    if not samples:
        raise RuntimeError(f"no usable player-gameweeks for {season}")
    train = [s for s in samples if s["gw"] < SPLIT_GW]
    test = [s for s in samples if s["gw"] >= SPLIT_GW]
    log(f"  train GW{START_GW}-{SPLIT_GW - 1}: {len(train)} | "
        f"test GW{SPLIT_GW}+: {len(test)}")

    elo_lambda = min(
        DAMPING_GRID, key=lambda L: mae(train, lambda s, L=L: s["rate"] * (1 + L * (s["elo"] - 1)))
    )

    def with_elo(s: dict) -> float:
        return s["rate"] * (1 + elo_lambda * (s["elo"] - 1))

    pos_lambda = min(
        DAMPING_GRID,
        key=lambda L: mae(train, lambda s, L=L: with_elo(s) * (1 + L * (s["factor"] - 1))),
    )
    log(f"  tuned on train only: elo damping {elo_lambda}, position damping {pos_lambda}")

    baseline = mae(test, with_elo)
    adjusted = mae(test, lambda s: with_elo(s) * (1 + pos_lambda * (s["factor"] - 1)))
    overall = (baseline - adjusted) / baseline * 100
    log(f"\n  HELD OUT: Elo-only MAE {baseline:.4f} -> with position factor "
        f"{adjusted:.4f}  ({overall:+.2f}%)")

    results = []
    print(f"\n  {'position':<10}{'n':>7}{'Elo MAE':>10}{'+factor':>11}{'incremental':>13}  verdict")
    print("  " + "-" * 60)
    for pos in (1, 2, 3, 4):
        subset = [s for s in test if s["pos"] == pos]
        if len(subset) < 80:
            continue
        b = mae(subset, with_elo)
        a = mae(subset, lambda s: with_elo(s) * (1 + pos_lambda * (s["factor"] - 1)))
        improvement = (b - a) / b * 100
        eligible = pos in ELIGIBLE
        passed = improvement > 0 and eligible
        print(f"  {POS_NAMES[pos]:<10}{len(subset):>7}{b:>10.4f}{a:>11.4f}"
              f"{improvement:>12.2f}%  {'PASS' if passed else 'excluded'}")
        results.append(
            {
                "season": season,
                "stat_type": f"opponent_points_conceded_{POS_NAMES[pos].lower()}",
                "confidence": "high" if passed else "watch",
                "flags_evaluated": len(subset),
                "baseline_mae": round(b, 6),
                "trend_mae": round(a, 6),
                "improvement_pct": round(improvement, 3),
                "hit_rate": None,
                "baseline_hit_rate": None,
                "passed": passed,
                "notes": (
                    f"held out GW{SPLIT_GW}+, damping {pos_lambda} tuned on "
                    f"GW{START_GW}-{SPLIT_GW - 1}; measured INCREMENTALLY over the "
                    "Elo fixture adjustment"
                ),
            }
        )

    with Run("opponent_backtest", season) as run:
        delete_where(
            "backtest_results",
            f"season=eq.{season}&stat_type=like.opponent_points_conceded_*",
        )
        run.rows = insert_rows("backtest_results", results)
    log(f"\n  recorded {len(results)} position result(s)")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "2025-26")
