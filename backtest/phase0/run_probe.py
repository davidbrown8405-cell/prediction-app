"""Phase 0 feasibility probe for ONE completed game ($0: Kalshi public + OddsPapi free key).

    python -m phase0.run_probe --date 2026-10-23 --away HOU --home SAS
    ODDSPAPI_KEY=... python -m phase0.run_probe --game-id 0022600xxx [--fixture-id ID]

Order follows the design: PBP first, then S6/S7 triggers from PBP, then prices.
Writes data/phase0/<game>/ (aligned CSVs + summary.json). Every HTTP response is cached."""
import argparse
import json
import os
import re
from pathlib import Path

import pandas as pd
import yaml

from . import kalshi as K
from . import oddspapi as O
from .align import join_snapshots_to_state
from .pbp import actions_to_frame, fetch_boxscore, fetch_pbp_raw, fetch_schedule, find_game_id
from .triggers import s6_candidates, s7_runs

ROOT = Path(__file__).resolve().parents[1]
PRE_GAME = pd.Timedelta(hours=3)


def season_of(event_ticker):
    """KXNBAGAME-25JAN15LALBOS -> '2024-25' (NBA seasons start in October)."""
    m = re.search(r"-(\d{2})([A-Z]{3})\d{2}", event_ticker)
    if not m:
        return None
    y, mon = 2000 + int(m.group(1)), K.MONTHS.index(m.group(2)) + 1
    start = y if mon >= 8 else y - 1
    return f"{start}-{str(start + 1)[2:]}"


def kalshi_probe(cfg, game, pbp, out):
    k = K.Kalshi(cfg["base_url"], cfg["min_request_interval_sec"])
    res = {"cutoff": k.cutoff()}
    series = k.nba_series(cfg["series_prefix"])
    res["nba_series"] = [{"ticker": s["ticker"], "title": s.get("title")} for s in series]

    # earliest season: walk every KXNBAGAME event (live + historical routes)
    evs = k.events(cfg["game_series"]) + (k.paged("/historical/events", "events",
                                                   series_ticker=cfg["game_series"], limit=200))
    seasons = pd.Series([season_of(e["event_ticker"]) for e in evs]).value_counts().sort_index()
    res["game_events_by_season"] = seasons.to_dict()

    suffix = K.event_suffix(game["tip"], game["away"], game["home"])
    lo, hi = game["tip"] - PRE_GAME, game["final"] + pd.Timedelta(minutes=30)
    markets_out, frames = [], []
    for s in series:
        ms = k.markets(f"{s['ticker']}-{suffix}")
        for m in ms:
            t = K.trades_to_frame(k.trades(m["ticker"], lo.timestamp(), hi.timestamp()), m["ticker"])
            c = K.candles_to_frame(k.candles(s["ticker"], m["ticker"], lo.timestamp(), hi.timestamp()), m["ticker"])
            liq = K.liquidity_summary(t, c, game["tip"], game["final"])
            markets_out.append({"series": s["ticker"], "ticker": m["ticker"],
                                "subtitle": m.get("yes_sub_title") or m.get("subtitle"),
                                "strike": K.market_strike(m), "result": m.get("result"),
                                "total_volume": m.get("volume_fp") or m.get("volume"), **liq})
            if len(t):
                frames.append(t.assign(series=s["ticker"], strike=K.market_strike(m)))
    res["markets"] = markets_out
    if frames:
        trades = pd.concat(frames, ignore_index=True)
        j = join_snapshots_to_state(trades, pbp)
        j.to_csv(out / "kalshi_trades_aligned.csv", index=False)
        # sanity: home-win contract price should rise with home margin
        home_ml = j[(j["series"] == cfg["game_series"]) & j["ticker"].str.endswith(f"-{game['home']}") & j["join_ok"]]
        res["home_ml_price_vs_margin_corr"] = (float(home_ml["yes_price"].corr(home_ml["margin_home"]))
                                               if len(home_ml) >= 10 else None)
        res["join_ok_rate"] = float(j["join_ok"].mean())
    return res


def oddspapi_probe(cfg, game, pbp, out, fixture_id):
    key = os.environ.get(cfg["key_env"])
    if not key:
        return {"skipped": f"{cfg['key_env']} not set"}
    api = O.OddsPapi(cfg["base_url"], key)
    res = {"requests": []}
    if not fixture_id:
        sports = api.get("/sports")
        res["requests"].append({"path": "/sports", "quota": O.quota_headers(api.last_headers)})
        bball = next(s for s in sports if "basketball" in json.dumps(s).lower())
        sport_id = bball.get("sportId", bball.get("id"))
        day = game["tip"].tz_convert("America/New_York")
        fx = api.get("/fixtures", sportId=sport_id, **{"from": f"{day:%Y-%m-%d}", "to": f"{day + pd.Timedelta(days=1):%Y-%m-%d}"})
        res["requests"].append({"path": "/fixtures", "quota": O.quota_headers(api.last_headers)})
        fx = fx if isinstance(fx, list) else fx.get("data", fx.get("fixtures", []))
        match = [f for f in fx if game["home_name"].lower() in json.dumps(f).lower()
                 and game["away_name"].lower() in json.dumps(f).lower()]
        if not match:
            return {**res, "error": "fixture not found", "fixtures_seen": len(fx)}
        fixture_id = match[0].get("fixtureId", match[0].get("id"))
    res["fixture_id"] = fixture_id
    body = api.historical_odds(fixture_id, cfg["bookmakers"])
    res["requests"].append({"path": "/historical-odds", "quota": O.quota_headers(api.last_headers)})
    snaps = O.flatten_snapshots(body)
    res["books_returned"] = sorted(snaps["book"].dropna().unique().tolist())
    res["pinnacle_present"] = "pinnacle" in res["books_returned"]
    res["inplay"] = O.inplay_summary(snaps, game["tip"], game["final"])
    if len(snaps):
        join_snapshots_to_state(snaps, pbp).to_csv(out / "oddspapi_aligned.csv", index=False)
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--game-id")
    ap.add_argument("--date", help="US/Eastern game date YYYY-MM-DD (with --away/--home)")
    ap.add_argument("--away")
    ap.add_argument("--home")
    ap.add_argument("--fixture-id", help="OddsPapi fixture id (skips /sports + /fixtures lookups)")
    ap.add_argument("--skip-oddspapi", action="store_true")
    args = ap.parse_args()
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text())

    gid = args.game_id or find_game_id(fetch_schedule(), args.date, args.away, args.home)
    box = fetch_boxscore(gid)
    pbp = actions_to_frame(fetch_pbp_raw(gid))
    h, a = box["homeTeam"], box["awayTeam"]
    game = {"game_id": gid, "home": h["teamTricode"], "away": a["teamTricode"],
            "home_name": f"{h['teamCity']} {h['teamName']}", "away_name": f"{a['teamCity']} {a['teamName']}",
            "tip": pbp["utc_ts"].min(), "final": pbp["utc_ts"].max(),
            "final_score": f"{a['score']}-{h['score']}"}
    out = ROOT / "data" / "phase0" / gid
    out.mkdir(parents=True, exist_ok=True)

    s6c, s7c = cfg["s6_early_deficit_favorite"], cfg["s7_fade_the_run"]
    trig = pd.concat([
        s6_candidates(pbp, s6c["deficit_variations"], s6c["periods"]),
        s7_runs(pbp, s7c["run_size_variations"], s7c["max_run_game_clock_sec"],
                s7c["max_wallclock_lag_sec"], s7c["exclude_q4_under_sec"])], ignore_index=True)
    trig.to_csv(out / "triggers.csv", index=False)

    summary = {
        "game": {k: str(v) for k, v in game.items()},
        "pbp": {"actions": len(pbp), "null_timeActual": int(pbp["utc_ts"].isna().sum()),
                "null_clock": int(pbp["clock_sec"].isna().sum()),
                "wall_clock_monotonic": bool(pbp["utc_ts"].is_monotonic_increasing)},
        "triggers": trig.drop(columns="price_windows").astype(str).to_dict("records"),
        "kalshi": kalshi_probe(cfg["kalshi"], game, pbp, out),
        "oddspapi": ({"skipped": "--skip-oddspapi"} if args.skip_oddspapi
                     else oddspapi_probe(cfg["oddspapi"], game, pbp, out, args.fixture_id)),
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    print(json.dumps(summary, indent=2, default=str))


if __name__ == "__main__":
    main()
