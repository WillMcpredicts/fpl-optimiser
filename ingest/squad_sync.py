"""Keep the stored squad in step with the real one, after each gameweek.

Everything else in the pipeline rolls forward on its own: prices, injuries,
finished-gameweek stats, the projection window, trends. The squad did not, which
meant that the moment a transfer was made in FPL every recommendation was being
built on a stale team -- the one thing that changes every week.

`entry/{id}/event/{gw}/picks/` becomes public once that gameweek's deadline has
passed, so from GW2 onward the last locked squad can be pulled automatically. It
is last week's team, not the live one, which is the right starting point: any
transfer made since is a change you are still deciding on.

A manually entered squad for the same or a later gameweek is never overwritten.
Manual entry is the only way to record a squad before a deadline, so it is
always the more current statement of intent.
"""
from __future__ import annotations

import os

from common import Run, get_json, log, select
from config import CURRENT_SEASON, FPL_API
from squad import from_fpl


def latest_finished_gameweek() -> int | None:
    boot = get_json(f"{FPL_API}/bootstrap-static/")
    finished = [e["id"] for e in boot["events"] if e.get("finished")]
    return max(finished) if finished else None


def current_squad_state(season: str) -> tuple[int | None, str | None]:
    rows = select("my_squad", f"season=eq.{season}&is_current=is.true&select=gw,source")
    if not rows:
        return None, None
    return rows[0]["gw"], rows[0]["source"]


def main(season: str = CURRENT_SEASON) -> None:
    manager_id = (os.environ.get("FPL_MANAGER_ID") or "").strip()
    if not manager_id:
        log("[squad_sync] FPL_MANAGER_ID not set; squad must be entered by hand")
        return

    gw = latest_finished_gameweek()
    if gw is None:
        log("[squad_sync] no gameweek finished yet; nothing to pull")
        return

    stored_gw, stored_source = current_squad_state(season)
    # A squad entered by hand for this gameweek or later reflects a decision the
    # public endpoint cannot see yet. Leave it alone.
    if stored_gw is not None and stored_source == "manual" and stored_gw > gw:
        log(f"[squad_sync] manual squad for GW{stored_gw} is ahead of the last "
            f"locked gameweek (GW{gw}); leaving it as is")
        return
    if stored_gw is not None and stored_source == "fpl_picks" and stored_gw > gw:
        log(f"[squad_sync] already synced to GW{stored_gw}; nothing newer")
        return

    with Run("squad_sync", season) as run:
        squad_id = from_fpl(int(manager_id), gw, season)
        run.rows = 15
        log(f"  pulled the GW{gw} locked squad into squad {squad_id}")


if __name__ == "__main__":
    main()
