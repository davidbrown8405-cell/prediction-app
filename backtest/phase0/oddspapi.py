"""OddsPapi v4 (free key). The response schema for /historical-odds isn't pinned down yet, so the
raw JSON is cached and flattened by walking it for price snapshots."""
import pandas as pd

from .http_cache import cached_get

_TS_KEYS = ("createdAt", "changedAt", "timestamp", "updatedAt", "ts")


class OddsPapi:
    def __init__(self, base_url, api_key):
        self.base, self.key = base_url.rstrip("/"), api_key
        self.last_headers = {}

    def get(self, path, **params):
        body, headers, _ = cached_get(f"{self.base}{path}", params={"apiKey": self.key, **params})
        self.last_headers = headers
        return body

    def historical_odds(self, fixture_id, bookmakers):
        return self.get("/historical-odds", fixtureId=fixture_id, bookmakers=",".join(bookmakers[:3]))


def quota_headers(headers):
    keys = ("limit", "remaining", "quota", "usage", "reset")
    return {k: v for k, v in headers.items() if any(w in k.lower() for w in keys)}


def flatten_snapshots(body):
    """Yield one row per price snapshot: path (book/market/outcome/...), utc_ts, price, extras.
    The path segments are positional: path[0] is the bookmaker under `bookmakers`."""
    rows = []

    def walk(node, path):
        if isinstance(node, dict):
            ts_key = next((k for k in _TS_KEYS if k in node), None)
            if ts_key and "price" in node:
                rows.append({"path": "/".join(path), "utc_ts": node[ts_key], "price": node["price"],
                             "active": node.get("active"), "limit": node.get("limit")})
                return
            for k, v in node.items():
                walk(v, path + [str(k)])
        elif isinstance(node, list):
            for v in node:
                walk(v, path)

    walk(body.get("bookmakers", body) if isinstance(body, dict) else body, [])
    df = pd.DataFrame(rows, columns=["path", "utc_ts", "price", "active", "limit"])
    if df.empty:
        return df.assign(book=None)
    ts = df["utc_ts"]
    numeric = pd.to_numeric(ts, errors="coerce")
    df["utc_ts"] = (pd.to_datetime(numeric, unit="ms" if numeric.median() > 1e11 else "s", utc=True)
                    if numeric.notna().all() else pd.to_datetime(ts, utc=True, format="ISO8601"))
    df["book"] = df["path"].str.split("/").str[0]
    return df.sort_values("utc_ts").reset_index(drop=True)


def inplay_summary(snaps, tip, final):
    out = {}
    for book, g in snaps.groupby("book"):
        live = g[(g["utc_ts"] > tip) & (g["utc_ts"] <= final)]
        out[book] = {"snapshots_total": len(g), "inplay_snapshots": len(live),
                     "inplay_outcome_paths": live["path"].nunique(),
                     "median_inplay_gap_sec": float(live.groupby("path")["utc_ts"].diff().dt.total_seconds().median())
                     if len(live) > 1 else None}
    return out
