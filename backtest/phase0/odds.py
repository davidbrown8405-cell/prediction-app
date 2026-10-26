"""The Odds API historical endpoint: snapshot fetch, flattening, and credit estimates."""
import pandas as pd

from .http_cache import cached_get

BASE = "https://api.the-odds-api.com/v4/historical/sports/{sport}/odds"
CREDITS_PER_REGION_MARKET = 10  # historical pricing per the-odds-api.com docs


def credits_per_call(n_regions, n_markets):
    return CREDITS_PER_REGION_MARKET * n_regions * n_markets


def estimate_season_credits(game_days, window_hours, interval_min, n_regions, n_markets):
    """One sport-wide historical call returns every NBA game at that instant, so cost
    scales with wall-clock coverage of game windows, not with number of games."""
    calls = game_days * int(window_hours * 60 / interval_min)
    return calls, calls * credits_per_call(n_regions, n_markets)


def fetch_snapshot(api_key, sport, iso_date, regions, markets):
    params = {"apiKey": api_key, "regions": ",".join(regions), "markets": ",".join(markets),
              "date": iso_date, "oddsFormat": "american", "dateFormat": "iso"}
    body, headers, from_cache = cached_get(BASE.format(sport=sport), params=params)
    return body, headers, from_cache


def snapshot_to_frame(body, event_id=None):
    """Flatten one historical response into rows (snapshot_ts, event, book, market, side, line, price)."""
    rows = []
    snap_ts = body["timestamp"]
    for ev in body.get("data", []):
        if event_id and ev["id"] != event_id:
            continue
        for bk in ev.get("bookmakers", []):
            for mk in bk.get("markets", []):
                for oc in mk.get("outcomes", []):
                    rows.append({
                        "snapshot_ts": snap_ts, "event_id": ev["id"],
                        "home_team": ev["home_team"], "away_team": ev["away_team"],
                        "commence_time": ev["commence_time"], "book": bk["key"],
                        "book_last_update": mk.get("last_update", bk.get("last_update")),
                        "market": mk["key"], "side": oc["name"],
                        "line": oc.get("point"), "price": oc.get("price"),
                    })
    df = pd.DataFrame(rows)
    if not df.empty:
        for c in ("snapshot_ts", "commence_time", "book_last_update"):
            df[c] = pd.to_datetime(df[c], utc=True)
    return df
