"""nba.com CDN liveData play-by-play -> tidy DataFrame with UTC wall-clock per event."""
import re

import pandas as pd

from .http_cache import cached_get

CDN = "https://cdn.nba.com/static/json/liveData"
HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://www.nba.com/"}


def fetch_boxscore(game_id):
    body, _, _ = cached_get(f"{CDN}/boxscore/boxscore_{game_id}.json", headers=HEADERS)
    return body["game"]


def fetch_pbp_raw(game_id):
    body, _, _ = cached_get(f"{CDN}/playbyplay/playbyplay_{game_id}.json", headers=HEADERS)
    return body["game"]["actions"]


def clock_to_seconds(clock):
    """ISO-8601 duration like 'PT11M37.00S' -> seconds remaining in period."""
    m = re.fullmatch(r"PT(?:(\d+)M)?(?:([\d.]+)S)?", clock or "")
    if not m:
        return None
    return int(m.group(1) or 0) * 60 + float(m.group(2) or 0)


def actions_to_frame(actions):
    df = pd.DataFrame(actions)
    out = pd.DataFrame({
        "action_number": df["actionNumber"],
        "period": df["period"].astype(int),
        "clock_sec": df["clock"].map(clock_to_seconds),
        "utc_ts": pd.to_datetime(df["timeActual"], utc=True, format="ISO8601"),
        "score_home": pd.to_numeric(df["scoreHome"]),
        "score_away": pd.to_numeric(df["scoreAway"]),
        "action_type": df["actionType"],
    })
    out["margin_home"] = out["score_home"] - out["score_away"]
    return out.sort_values(["utc_ts", "action_number"]).reset_index(drop=True)
