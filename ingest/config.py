"""Shared configuration for the ingestion jobs."""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env.local")

# The season the live game is in, in the two formats the sources disagree on.
CURRENT_SEASON = os.environ.get("FPL_SEASON", "2026-27")
# vaastav uses '2025-26'; FPL-Core-Insights uses '2025-2026'.
VAASTAV_SEASONS = ["2025-26"]

FPL_API = "https://fantasy.premierleague.com/api"
VAASTAV_RAW = "https://raw.githubusercontent.com/vaastav/Fantasy-Premier-League/master/data"
CORE_INSIGHTS_RAW = "https://raw.githubusercontent.com/olbauday/FPL-Core-Insights/HEAD/data"

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")

# FPL position ids.
GK, DEF, MID, FWD = 1, 2, 3, 4
POSITION_NAMES = {GK: "GKP", DEF: "DEF", MID: "MID", FWD: "FWD"}


def core_insights_season(season: str) -> str:
    """'2025-26' -> '2025-2026', the layout FPL-Core-Insights uses."""
    start, end = season.split("-")
    return f"{start}-{start[:2]}{end}"
