"""Shared configuration for the ingestion jobs."""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env.local")

# The season the live game is in, in the two formats the sources disagree on.
CURRENT_SEASON = os.environ.get("FPL_SEASON", "2026-27")
# vaastav uses '2025-26'; FPL-Core-Insights uses '2025-2026'.
# Newest first. Three seasons of player history, each discounted by age.
VAASTAV_SEASONS = ["2025-26", "2024-25", "2023-24"]

# Each season back counts for this much of the one after it. A player's 2023-24
# form is real evidence but weaker than last season's, and this decays it
# geometrically rather than treating all history as equal.
SEASON_DECAY = 0.55

# Defensive Contribution was introduced in 2025/26 and is simply absent from
# earlier vaastav data -- the columns do not exist, so it cannot be derived.
# Rows from these seasons are excluded from DefCon rate maths rather than
# counted as zero, which would drag every defender's rate down.
SEASONS_WITHOUT_DEFCON = {"2024-25", "2023-24"}


def season_weight(season: str, current: str = CURRENT_SEASON) -> float:
    """Recency weight for a season's rows. The live season weighs 1.0."""
    if season == current:
        return 1.0
    try:
        age = int(current.split("-")[0]) - int(season.split("-")[0])
    except ValueError:
        return SEASON_DECAY
    return SEASON_DECAY ** max(1, age)

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
