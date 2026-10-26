"""Join odds snapshots to the play-by-play state at each snapshot's UTC timestamp."""
import pandas as pd


def join_snapshots_to_state(odds, pbp, max_staleness_sec=180, ts_col="utc_ts"):
    """As-of join: each price row gets the latest PBP event at or before its timestamp.

    `ts_col` is the time the price is valid as of (Kalshi trade time, OddsPapi changedAt).
    If a `snapshot_ts` column exists it fills gaps in `ts_col`.
    `join_ok` is False before tip-off and after the final event. `stale` marks rows whose
    last event is more than `max_staleness_sec` old: the score is still right then (dead ball,
    timeout, halftime), but PBP may lag the feed, so it is reported rather than dropped."""
    o = odds.copy()
    o["_ts"] = o[ts_col].fillna(o["snapshot_ts"]) if "snapshot_ts" in o else o[ts_col]
    o = o.sort_values("_ts")
    p = pbp.sort_values("utc_ts")[["utc_ts", "period", "clock_sec", "score_home",
                                    "score_away", "margin_home"]].rename(columns={"utc_ts": "pbp_utc_ts"})
    o = o.drop(columns=[c for c in p.columns if c in o and c != "pbp_utc_ts"])
    joined = pd.merge_asof(o, p, left_on="_ts", right_on="pbp_utc_ts", direction="backward")
    lag = (joined["_ts"] - joined["pbp_utc_ts"]).dt.total_seconds()
    joined["state_lag_sec"] = lag
    game_over = joined["_ts"] > pbp["utc_ts"].max()
    joined["join_ok"] = lag.notna() & ~game_over
    joined["stale"] = joined["join_ok"] & (lag > max_staleness_sec)
    return joined.drop(columns="_ts")
