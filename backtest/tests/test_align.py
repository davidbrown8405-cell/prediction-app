import pandas as pd

from phase0.align import join_snapshots_to_state
from phase0.pbp import actions_to_frame, clock_to_seconds

T = lambda s: pd.Timestamp(f"2025-01-01T{s}Z")


def _pbp():
    return pd.DataFrame({
        "utc_ts": [T("00:00:00"), T("00:01:00"), T("00:05:00"), T("02:20:00")],
        "period": [1, 1, 1, 4], "clock_sec": [720, 690, 600, 0],
        "score_home": [0, 2, 10, 110], "score_away": [0, 0, 2, 100],
    }).assign(margin_home=lambda d: d.score_home - d.score_away)


def _odds(times):
    return pd.DataFrame({"snapshot_ts": [T(t) for t in times],
                         "book_last_update": [T(t) for t in times], "line": -1.0})


def test_asof_uses_latest_event_at_or_before():
    j = join_snapshots_to_state(_odds(["00:01:00", "00:03:59"]), _pbp())
    assert j["margin_home"].tolist() == [2, 2]  # exact match counts; never peeks forward
    assert j["join_ok"].all()


def test_pregame_and_postgame_snapshots_fail_join():
    j = join_snapshots_to_state(_odds(["23:59:00", "02:30:00"]), _pbp())
    assert not j["join_ok"].any()


def test_stale_state_flagged():
    j = join_snapshots_to_state(_odds(["00:09:00"]), _pbp(), max_staleness_sec=180)
    assert j["state_lag_sec"].iloc[0] == 240 and not j["join_ok"].iloc[0]


def test_book_last_update_preferred_over_snapshot_time():
    o = _odds(["00:06:00"]).assign(book_last_update=[T("00:01:30")])
    j = join_snapshots_to_state(o, _pbp())
    assert j["margin_home"].iloc[0] == 2  # price was set before the 10-2 score


def test_clock_parse():
    assert clock_to_seconds("PT11M37.00S") == 697
    assert clock_to_seconds("PT00M00.50S") == 0.5
    assert clock_to_seconds("") is None


def test_actions_to_frame_sorts_and_computes_margin():
    acts = [
        {"actionNumber": 2, "period": 1, "clock": "PT11M00.00S", "timeActual": "2025-01-01T00:01:00.0Z",
         "scoreHome": "2", "scoreAway": "0", "actionType": "2pt"},
        {"actionNumber": 1, "period": 1, "clock": "PT12M00.00S", "timeActual": "2025-01-01T00:00:00.0Z",
         "scoreHome": "0", "scoreAway": "0", "actionType": "period"},
    ]
    df = actions_to_frame(acts)
    assert df["action_number"].tolist() == [1, 2] and df["margin_home"].tolist() == [0, 2]
