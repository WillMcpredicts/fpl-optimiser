"""Import my squad.

Two routes, because FPL gives no public access to a live, pre-deadline squad:

  manual  -- the fallback the brief asked for, and the ONLY option before GW1
             has been played. `my-team/{id}/` returns 403 without a session
             cookie and this project deliberately does not handle FPL login.

  fpl     -- from GW2 onward, `entry/{id}/event/{gw}/picks/` becomes public once
             that gameweek's deadline has passed. That is last gameweek's LOCKED
             squad, not the live one, so it is a starting point to correct by
             hand rather than a source of truth.

Purchase prices are not in any public endpoint either (they live behind the same
auth as my-team), so selling values fall back to current price. That is exact
for a player bought at today's price and understates any profit otherwise --
which makes affordability conservative rather than optimistic.
"""
from __future__ import annotations

import json
import sys

from common import Run, get_json, log, select, upsert
from config import CURRENT_SEASON, FPL_API

# FPL returns half of any price rise, rounded down to 0.1m
# (`transfers_sell_on_fee = 0.5` in the live game settings).
def selling_price(purchase: int | None, now_cost: int) -> int:
    if purchase is None or now_cost <= purchase:
        return now_cost
    return purchase + (now_cost - purchase) // 2


def _clear_current(season: str) -> None:
    """Only one squad is 'current'; the rest are history."""
    from common import SESSION, SUPABASE_URL, _headers

    r = SESSION.patch(
        f"{SUPABASE_URL}/rest/v1/my_squad?season=eq.{season}&is_current=is.true",
        json={"is_current": False},
        headers=_headers("return=minimal"),
        timeout=60,
    )
    if r.status_code >= 400:
        raise RuntimeError(f"could not clear current squad: {r.text[:300]}")


def save(
    season: str,
    gw: int,
    source: str,
    picks: list[dict],
    bank: int,
    free_transfers: int,
    squad_value: int | None = None,
    chips_available: list[str] | None = None,
    chips_used: list[str] | None = None,
) -> int:
    """Write a squad and its 15 picks. Returns the new squad id."""
    from common import SESSION, SUPABASE_URL, _headers

    if len(picks) != 15:
        raise ValueError(f"a squad is 15 players, got {len(picks)}")

    _clear_current(season)
    r = SESSION.post(
        f"{SUPABASE_URL}/rest/v1/my_squad",
        json={
            "season": season,
            "gw": gw,
            "source": source,
            "bank": bank,
            "squad_value": squad_value,
            "free_transfers": free_transfers,
            "chips_available": chips_available or [],
            "chips_used": chips_used or [],
            "is_current": True,
        },
        headers=_headers("return=representation"),
        timeout=60,
    )
    if r.status_code >= 400:
        raise RuntimeError(f"could not save squad: {r.text[:400]}")
    squad_id = r.json()[0]["id"]

    for p in picks:
        p["squad_id"] = squad_id
    upsert("my_squad_picks", picks, on_conflict="squad_id,player_id")
    return squad_id


def build_picks(
    player_ids: list[int],
    players_by_id: dict[int, dict],
    purchase_prices: dict[int, int] | None = None,
    captain: int | None = None,
    vice: int | None = None,
) -> list[dict]:
    purchase_prices = purchase_prices or {}
    picks = []
    for order, pid in enumerate(player_ids, start=1):
        player = players_by_id.get(pid)
        if not player:
            raise ValueError(f"player id {pid} is not in this season's player list")
        now_cost = player["now_cost"]
        purchase = purchase_prices.get(pid)
        picks.append(
            {
                "player_id": pid,
                "player_code": player["code"],
                "position": order,
                "is_captain": pid == captain,
                "is_vice_captain": pid == vice,
                "purchase_price": purchase if purchase is not None else now_cost,
                "selling_price": selling_price(purchase, now_cost),
            }
        )
    return picks


def validate(picks: list[dict], players_by_id: dict[int, dict], bank: int) -> list[str]:
    """Check the squad against FPL's own rules. Returns a list of problems."""
    problems: list[str] = []
    ids = [p["player_id"] for p in picks]
    if len(set(ids)) != len(ids):
        problems.append("the same player appears more than once")

    by_position: dict[int, int] = {}
    by_team: dict[int, int] = {}
    total = 0
    for p in picks:
        player = players_by_id[p["player_id"]]
        by_position[player["element_type"]] = by_position.get(player["element_type"], 0) + 1
        by_team[player["team_id"]] = by_team.get(player["team_id"], 0) + 1
        total += p["selling_price"]

    expected = {1: 2, 2: 5, 3: 5, 4: 3}
    names = {1: "goalkeepers", 2: "defenders", 3: "midfielders", 4: "forwards"}
    for pos, want in expected.items():
        got = by_position.get(pos, 0)
        if got != want:
            problems.append(f"{got} {names[pos]}, expected {want}")

    over = [t for t, n in by_team.items() if n > 3]
    if over:
        problems.append(f"more than 3 players from one club ({len(over)} club(s) over the limit)")

    if total + bank > 1000:
        problems.append(
            f"squad value {total / 10:.1f} plus bank {bank / 10:.1f} exceeds the 100.0 budget"
        )
    return problems


def from_fpl(manager_id: int, gw: int, season: str = CURRENT_SEASON) -> int:
    """Pull the last locked squad from the public picks endpoint.

    Unverified against a live payload: the endpoint 404s until a gameweek has
    actually been played, so this is written to the documented shape and logs
    loudly rather than guessing if a field is missing.
    """
    picks_url = f"{FPL_API}/entry/{manager_id}/event/{gw}/picks/"
    data = get_json(picks_url)
    if not isinstance(data, dict) or "picks" not in data:
        raise RuntimeError(
            f"{picks_url} did not return a squad. Before a gameweek has been "
            "played this endpoint 404s -- use manual entry."
        )

    history = data.get("entry_history") or {}
    bank = history.get("bank")
    if bank is None:
        log("  entry_history.bank missing; defaulting bank to 0")
        bank = 0

    players = select("players", f"season=eq.{season}&select=*")
    players_by_id = {p["id"]: p for p in players}

    raw = sorted(data["picks"], key=lambda p: p.get("position", 0))
    captain = next((p["element"] for p in raw if p.get("is_captain")), None)
    vice = next((p["element"] for p in raw if p.get("is_vice_captain")), None)
    built = build_picks(
        [p["element"] for p in raw], players_by_id, captain=captain, vice=vice
    )

    problems = validate(built, players_by_id, bank)
    for p in problems:
        log(f"  warning: {p}")

    return save(
        season,
        gw + 1,
        "fpl_picks",
        built,
        bank,
        free_transfers=1,
        squad_value=history.get("value"),
    )


def from_manual(
    player_ids: list[int],
    bank: int,
    free_transfers: int,
    gw: int,
    season: str = CURRENT_SEASON,
    captain: int | None = None,
    vice: int | None = None,
    purchase_prices: dict[int, int] | None = None,
) -> tuple[int, list[str]]:
    players = select("players", f"season=eq.{season}&select=*")
    players_by_id = {p["id"]: p for p in players}
    built = build_picks(player_ids, players_by_id, purchase_prices, captain, vice)
    problems = validate(built, players_by_id, bank)
    squad_id = save(
        season,
        gw,
        "manual",
        built,
        bank,
        free_transfers,
        squad_value=sum(p["selling_price"] for p in built),
    )
    return squad_id, problems


def resolve_names(names: list[str], season: str = CURRENT_SEASON) -> list[int]:
    """Map web names to element ids, failing loudly on anything ambiguous."""
    players = select("players", f"season=eq.{season}&select=id,web_name,team_id,now_cost")
    by_name: dict[str, list[dict]] = {}
    for p in players:
        by_name.setdefault(p["web_name"].lower(), []).append(p)

    ids, errors = [], []
    for name in names:
        matches = by_name.get(name.strip().lower(), [])
        if not matches:
            errors.append(f"no player called {name!r}")
        elif len(matches) > 1:
            errors.append(
                f"{name!r} is ambiguous: ids {[m['id'] for m in matches]}"
            )
        else:
            ids.append(matches[0]["id"])
    if errors:
        raise ValueError("; ".join(errors))
    return ids


def main() -> None:
    """CLI:

    python ingest/squad.py fpl <manager_id> <gw>
    python ingest/squad.py manual <path-to-json>

    The manual JSON looks like:
      {"gw": 1, "bank": 5, "free_transfers": 1,
       "players": ["Raya", "Gabriel", ...], "captain": "Haaland"}
    """
    if len(sys.argv) < 3:
        print(main.__doc__)
        raise SystemExit(2)

    mode = sys.argv[1]
    with Run(f"squad_{mode}", CURRENT_SEASON) as run:
        if mode == "fpl":
            squad_id = from_fpl(int(sys.argv[2]), int(sys.argv[3]))
            log(f"  imported squad {squad_id} from FPL")
        elif mode == "manual":
            spec = json.loads(open(sys.argv[2]).read())
            ids = (
                spec["player_ids"]
                if "player_ids" in spec
                else resolve_names(spec["players"])
            )
            captain = spec.get("captain")
            captain_id = (
                captain if isinstance(captain, int) else
                (resolve_names([captain])[0] if captain else None)
            )
            squad_id, problems = from_manual(
                ids,
                int(spec.get("bank", 0)),
                int(spec.get("free_transfers", 1)),
                int(spec["gw"]),
                captain=captain_id,
            )
            for p in problems:
                log(f"  warning: {p}")
            log(f"  saved squad {squad_id}")
        else:
            print(main.__doc__)
            raise SystemExit(2)
        run.rows = 15


if __name__ == "__main__":
    main()
