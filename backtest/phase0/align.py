"""Join odds snapshots to the play-by-play state at each snapshot's UTC timestamp."""
import pandas as pd


def join_snapshots_to_state(odds, pbp, max_staleness_sec=180, ts_col="book_last_update"):
    """As-of join: each odds row gets the latest PBP event at or before its timestamp.

    `ts_col` is the time the price is valid as of. We prefer the book's own last_update
    over the snapshot capture time, since a book can sit on a stale price across snapshots.
    Rows before tip-off or with no event within `max_staleness_sec` get state NaN and
    `join_ok=False` (staleness is allowed to be long only during dead-ball stretches; the
    threshold is a sanity guard, not a rule)."""
    o = odds.copy()
    o["_ts"] = o[ts_col].fillna(o["snapshot_ts"]) if ts_col in o else o["snapshot_ts"]
    o = o.sort_values("_ts")
    p = pbp.sort_values("utc_ts")[["utc_ts", "period", "clock_sec", "score_home",
                                    "score_away", "margin_home"]]
    joined = pd.merge_asof(o, p, left_on="_ts", right_on="utc_ts", direction="backward")
    lag = (joined["_ts"] - joined["utc_ts"]).dt.total_seconds()
    joined["state_lag_sec"] = lag
    game_over = joined["_ts"] > pbp["utc_ts"].max()
    joined["join_ok"] = lag.notna() & (lag <= max_staleness_sec) & ~game_over
    return joined.drop(columns="_ts").rename(columns={"utc_ts": "pbp_utc_ts"})
