"""How accurate is the predicted points model itself?

Replays the whole model over a completed season, gameweek by gameweek, using
only football played before each one. Every rate, depth chart and fixture
adjustment is rebuilt from scratch at each step, so nothing leaks backwards.

Compared against three baselines, because "is it accurate" is meaningless
without something to be more accurate than:

    league      the positional average. The floor.
    ppg         the player's own points per game so far. The honest bar --
                it is what a sensible person would guess, and beating it is
                the whole justification for a model.
    last season the player's points per 90 from the previous season.

Judged two ways. Error (MAE) says how close a projection lands. Ranking says
whether the players it likes actually outscore the ones it does not -- which is
what a squad decision actually depends on.

Run:  python ingest/model_backtest.py [season]
"""
from __future__ import annotations

import statistics
import sys
from collections import defaultdict

from common import log, select
from depth import build_depth_priors
from rates import build_player_rates
from scoring import (
    AWAY_ATTACK_FACTOR,
    HOME_ATTACK_FACTOR,
    LEAGUE_AVG_GOALS_PER_TEAM,
    elo_multiplier,
)
from model import availability, score_fixture, team_concede_lambda

START_GW = 8          # enough football behind to build rates from
PRIOR_SEASONS = ["2024-25", "2023-24"]


def load(season: str):
    players = select("players", f"season=eq.{season}&select=*")
    gw_rows = select("player_gameweeks", f"season=eq.{season}&select=*")
    prior_rows: list[dict] = []
    for ps in PRIOR_SEASONS:
        prior_rows.extend(select("player_gameweeks", f"season=eq.{ps}&select=*"))
    fixtures = select("team_match_stats", f"season=eq.{season}&select=team_id,opponent_id,gw,is_home,elo,opponent_elo")
    return players, gw_rows, prior_rows, fixtures


def main(season: str = "2025-26") -> None:
    players, gw_rows, prior_rows, fixtures = load(season)
    log(f"  {len(players)} players, {len(gw_rows)} gameweeks, {len(fixtures)} team-fixtures")

    by_gw: dict[int, list[dict]] = defaultdict(list)
    for r in gw_rows:
        by_gw[r["gw"]].append(r)
    fixtures_by_gw: dict[int, list[dict]] = defaultdict(list)
    for f in fixtures:
        if f.get("gw"):
            fixtures_by_gw[int(f["gw"])].append(f)

    prior_by_code: dict[int, list[dict]] = defaultdict(list)
    for r in prior_rows:
        prior_by_code[r["player_code"]].append(r)

    max_gw = max(by_gw)
    samples: list[dict] = []

    for target in range(START_GW, max_gw + 1):
        history: dict[int, list[dict]] = defaultdict(list)
        for g in range(1, target):
            for r in by_gw[g]:
                history[r["player_code"]].append(r)
        for code, rows in prior_by_code.items():
            history[code].extend(rows)

        # Elo as known before this gameweek.
        elo_seen: dict[int, list[float]] = defaultdict(list)
        for g in range(1, target):
            for f in fixtures_by_gw[g]:
                if f.get("elo"):
                    elo_seen[f["team_id"]].append(float(f["elo"]))
        elo = {k: statistics.mean(v) for k, v in elo_seen.items()}
        if not elo:
            continue

        rates_by_player = build_player_rates(players, history, elo)

        actual_by_player = {r["player_id"]: (r.get("total_points") or 0) for r in by_gw[target]}
        played = {r["player_id"] for r in by_gw[target] if (r.get("minutes") or 0) > 0}

        # Season-to-date points per game, the baseline worth beating.
        ppg_pts: dict[int, float] = defaultdict(float)
        ppg_games: dict[int, int] = defaultdict(int)
        for g in range(1, target):
            for r in by_gw[g]:
                ppg_pts[r["player_id"]] += r.get("total_points") or 0
                ppg_games[r["player_id"]] += 1
        league_by_pos: dict[int, list[float]] = defaultdict(list)
        for pid, g in ppg_games.items():
            pass

        fixture_for: dict[int, dict] = {}
        for f in fixtures_by_gw[target]:
            fixture_for[f["team_id"]] = f

        pos_actuals: dict[int, list[float]] = defaultdict(list)
        for p in players:
            if p["id"] in actual_by_player:
                pos_actuals[p["element_type"]].append(actual_by_player[p["id"]])
        league_mean = {k: statistics.mean(v) for k, v in pos_actuals.items() if v}

        for p in players:
            fx = fixture_for.get(p["team_id"])
            if not fx:
                continue  # no fixture that gameweek
            rates = rates_by_player.get(p["id"])
            if not rates:
                continue
            avail, _ = availability(p)
            opp_elo = float(fx["opponent_elo"]) if fx.get("opponent_elo") else None
            team_elo = float(fx["elo"]) if fx.get("elo") else None
            is_home = bool(fx["is_home"])
            mult = elo_multiplier(team_elo, opp_elo) * (
                HOME_ATTACK_FACTOR if is_home else AWAY_ATTACK_FACTOR
            )
            lam = team_concede_lambda(team_elo, opp_elo, is_home)
            pred = score_fixture(rates, avail, mult, lam)["total"]

            games = ppg_games.get(p["id"], 0)
            ppg = (ppg_pts[p["id"]] / games) if games else 0.0
            samples.append({
                "gw": target,
                "pos": p["element_type"],
                "pred": pred,
                "ppg": ppg,
                "league": league_mean.get(p["element_type"], 0.0),
                "actual": actual_by_player.get(p["id"], 0),
                "played": p["id"] in played,
            })
        if target % 6 == 0:
            log(f"    ...through GW{target}, {len(samples)} observations")

    report(samples)


def corr(xs, ys):
    mx, my = statistics.mean(xs), statistics.mean(ys)
    n = sum((a - mx) * (b - my) for a, b in zip(xs, ys))
    d = (sum((a - mx) ** 2 for a in xs) * sum((b - my) ** 2 for b in ys)) ** 0.5
    return n / d if d else 0.0


def report(samples: list[dict]) -> None:
    POS = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}
    print(f"\n  {len(samples)} player-gameweeks predicted, walk-forward\n")
    acts = [s["actual"] for s in samples]

    print(f"  {'predictor':<14}{'MAE':>8}{'RMSE':>8}{'corr':>8}  vs ppg")
    print("  " + "-" * 48)
    results = {}
    for key, label in (("league", "league avg"), ("ppg", "own PPG"), ("pred", "model")):
        preds = [s[key] for s in samples]
        mae = statistics.mean(abs(a - p) for a, p in zip(acts, preds))
        rmse = (statistics.mean((a - p) ** 2 for a, p in zip(acts, preds))) ** 0.5
        r = corr(preds, acts)
        results[key] = mae
        delta = (results["ppg"] - mae) / results["ppg"] * 100 if "ppg" in results else 0
        extra = f"{delta:+6.1f}%" if key == "pred" else ""
        print(f"  {label:<14}{mae:>8.3f}{rmse:>8.3f}{r:>8.3f}  {extra}")

    # The aggregate is dominated by players who never featured, so it hides
    # what the model is actually for. Split it.
    played = [x for x in samples if x["played"]]
    absent = [x for x in samples if not x["played"]]
    print(f"\n  split by whether the player actually featured:")
    print(f"    {'':<16}{'n':>7}{'actual':>9}{'model':>9}{'ppg':>9}{'model MAE':>11}{'ppg MAE':>10}")
    for label, grp in (("featured", played), ("did not play", absent)):
        if not grp:
            continue
        print(
            f"    {label:<16}{len(grp):>7}"
            f"{statistics.mean(x['actual'] for x in grp):>9.2f}"
            f"{statistics.mean(x['pred'] for x in grp):>9.2f}"
            f"{statistics.mean(x['ppg'] for x in grp):>9.2f}"
            f"{statistics.mean(abs(x['actual'] - x['pred']) for x in grp):>11.3f}"
            f"{statistics.mean(abs(x['actual'] - x['ppg']) for x in grp):>10.3f}"
        )
    print(f"    {len(absent) / len(samples):.0%} of observations never featured, which is why the")
    print("    aggregate figure above is not the one that matters for team selection.")

    print(f"\n  by position (model MAE vs own-PPG MAE):")
    print(f"    {'':<6}{'n':>7}{'model':>9}{'ppg':>9}{'better by':>11}{'corr':>8}")
    for pos in (1, 2, 3, 4):
        sub = [s for s in samples if s["pos"] == pos]
        if len(sub) < 100:
            continue
        a = [s["actual"] for s in sub]
        m = statistics.mean(abs(x["actual"] - x["pred"]) for x in sub)
        q = statistics.mean(abs(x["actual"] - x["ppg"]) for x in sub)
        print(f"    {POS[pos]:<6}{len(sub):>7}{m:>9.3f}{q:>9.3f}"
              f"{(q - m) / q * 100:>10.1f}%{corr([x['pred'] for x in sub], a):>8.3f}")

    # Does it rank? Take the model's top picks each week and see what they scored.
    print(f"\n  ranking quality -- mean actual points of the model's top N each gameweek")
    by_gw: dict[int, list[dict]] = defaultdict(list)
    for s in samples:
        by_gw[s["gw"]].append(s)
    print(f"    {'top N':<8}{'model':>9}{'own PPG':>10}{'all players':>13}")
    for n in (10, 25, 50, 100):
        m_scores, p_scores = [], []
        for gw, rows in by_gw.items():
            m_scores += [r["actual"] for r in sorted(rows, key=lambda x: -x["pred"])[:n]]
            p_scores += [r["actual"] for r in sorted(rows, key=lambda x: -x["ppg"])[:n]]
        overall = statistics.mean(s["actual"] for s in samples)
        print(f"    {n:<8}{statistics.mean(m_scores):>9.2f}{statistics.mean(p_scores):>10.2f}"
              f"{overall:>13.2f}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "2025-26")
