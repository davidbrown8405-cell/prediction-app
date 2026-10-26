"""Phase 0 feasibility probe for ONE game.

    python -m phase0.run_probe --estimate-only
    ODDS_API_KEY=... python -m phase0.run_probe --game-id 0022400xxx --yes

Pulls the game's PBP + boxscore from the nba.com CDN, then walks The Odds API historical
snapshots from tip-off to final via `next_timestamp`, and writes an aligned CSV plus a
summary (snapshot interval, books, in-play presence, spread-vs-margin correlation)."""
import argparse
import json
import os
from datetime import timedelta
from pathlib import Path

import pandas as pd
import yaml

from . import odds as oddsmod
from .align import join_snapshots_to_state
from .pbp import actions_to_frame, fetch_boxscore, fetch_pbp_raw

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "phase0"


def print_estimate(cfg):
    o = cfg["odds"]
    per_call = oddsmod.credits_per_call(len(o["regions"]), len(o["markets"]))
    print(f"credits per historical call: {per_call} ({len(o['regions'])} regions x {len(o['markets'])} markets x 10)")
    # ~165 regular-season game days + ~60 playoff/play-in days; window = first tip to last final.
    for label, days, hours in [("low", 210, 6.5), ("mid", 225, 7.5), ("high", 235, 9.0)]:
        calls, credits = oddsmod.estimate_season_credits(days, hours, 5, len(o["regions"]), len(o["markets"]))
        print(f"  {label}: {calls:,} calls/season -> {credits:,} credits/season, {3 * credits:,} for 3 seasons")
    print(f"  single-game probe (~2h30m at 5 min): ~{30 * per_call:,} credits")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--game-id")
    ap.add_argument("--estimate-only", action="store_true")
    ap.add_argument("--yes", action="store_true", help="confirm spending API credits")
    ap.add_argument("--max-calls", type=int, default=40)
    args = ap.parse_args()
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text())
    print_estimate(cfg)
    if args.estimate_only:
        return
    if not args.game_id:
        ap.error("--game-id required")

    box = fetch_boxscore(args.game_id)
    pbp = actions_to_frame(fetch_pbp_raw(args.game_id))
    home, away = box["homeTeam"], box["awayTeam"]
    home_name = f"{home['teamCity']} {home['teamName']}"
    away_name = f"{away['teamCity']} {away['teamName']}"
    print(f"\nPBP: {len(pbp)} actions, {pbp['utc_ts'].min()} -> {pbp['utc_ts'].max()}, "
          f"null timeActual: {pbp['utc_ts'].isna().sum()}")

    if not args.yes:
        print("\nRe-run with --yes (and ODDS_API_KEY set) to pull odds snapshots.")
        return
    key = os.environ["ODDS_API_KEY"]
    o = cfg["odds"]
    # pre-game closing line: snapshot just before tip
    cursor = (pbp["utc_ts"].min() - timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%SZ")
    end = pbp["utc_ts"].max() + timedelta(minutes=10)
    frames, snaps, remaining = [], [], None
    for _ in range(args.max_calls):
        body, headers, cached = oddsmod.fetch_snapshot(key, o["sport"], cursor, o["regions"], o["markets"])
        remaining = headers.get("x-requests-remaining", remaining)
        snaps.append(body["timestamp"])
        df = oddsmod.snapshot_to_frame(body)
        df = df[(df["home_team"] == home_name) & (df["away_team"] == away_name)]
        frames.append(df)
        nxt = body.get("next_timestamp")
        if not nxt or pd.Timestamp(nxt) > end:
            break
        cursor = nxt
    odds = pd.concat(frames, ignore_index=True)
    snap_ts = pd.to_datetime(pd.Series(snaps), utc=True)
    gaps = snap_ts.diff().dt.total_seconds().dropna()

    joined = join_snapshots_to_state(odds, pbp, cfg["alignment"]["max_staleness_sec"])
    OUT.mkdir(parents=True, exist_ok=True)
    joined.to_csv(OUT / f"aligned_{args.game_id}.csv", index=False)

    inplay = joined[joined["join_ok"]]
    home_spreads = inplay[(inplay["market"] == "spreads") & (inplay["side"] == home_name)]
    # A home team leading by m should be laid roughly -m: expect a strongly negative correlation.
    corr = {b: g["line"].corr(g["margin_home"]) for b, g in home_spreads.groupby("book") if len(g) >= 5}
    summary = {
        "game": f"{away_name} @ {home_name}", "snapshots": len(snaps),
        "interval_sec_median": float(gaps.median()) if len(gaps) else None,
        "interval_sec_max": float(gaps.max()) if len(gaps) else None,
        "books": sorted(odds["book"].unique().tolist()),
        "inplay_rows_by_book": inplay.groupby("book").size().to_dict(),
        "pinnacle_inplay": bool((inplay["book"] == "pinnacle").any()),
        "spread_vs_margin_corr_by_book": corr,
        "join_ok_rate": float(joined["join_ok"].mean()),
        "credits_remaining": remaining,
    }
    (OUT / f"summary_{args.game_id}.json").write_text(json.dumps(summary, indent=2, default=str))
    print(json.dumps(summary, indent=2, default=str))


if __name__ == "__main__":
    main()
