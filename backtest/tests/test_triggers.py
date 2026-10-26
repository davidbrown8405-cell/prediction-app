import pandas as pd

from phase0.triggers import elapsed_game_sec, first_price_in_windows, s6_candidates, s7_runs

T0 = pd.Timestamp("2026-10-23T00:00:00Z")


def pbp(rows):
    """rows: (wall_sec, period, clock_sec, home, away)"""
    df = pd.DataFrame(rows, columns=["w", "period", "clock_sec", "score_home", "score_away"])
    df["utc_ts"] = T0 + pd.to_timedelta(df["w"], unit="s")
    df["action_number"] = range(len(df))
    df["margin_home"] = df["score_home"] - df["score_away"]
    return df.drop(columns="w")


def test_elapsed_across_ot():
    assert elapsed_game_sec([1, 4, 5, 6], [720, 0, 300, 100]).tolist() == [0, 2880, 2880, 3380]


def test_s7_net_run_within_three_minutes():
    # away goes 12-2 between clock 600 and 430 (170 s): net 10
    rows = [(0, 1, 720, 0, 0), (60, 1, 600, 0, 3), (120, 1, 560, 2, 3), (200, 1, 520, 2, 6),
            (300, 1, 480, 2, 9), (400, 1, 430, 2, 12)]
    r = s7_runs(pbp(rows), run_sizes=(10,))
    assert len(r) == 1
    row = r.iloc[0]
    assert row.running_team == "away" and row.bet_team == "home" and row.run_net == 10
    assert row.trigger_utc == T0 + pd.Timedelta(seconds=400)  # fires when it first qualifies
    assert row.price_windows[0][1] - row.price_windows[0][0] == pd.Timedelta(minutes=5)


def test_s7_too_slow_is_not_a_run():
    rows = [(0, 1, 720, 0, 0), (60, 1, 700, 5, 0), (500, 1, 450, 10, 0)]  # 250 s of game clock
    assert s7_runs(pbp(rows), run_sizes=(10,)).empty


def test_s7_one_trigger_per_team_and_late_q4_excluded():
    rows = [(0, 1, 720, 0, 0), (10, 1, 700, 10, 0), (20, 1, 690, 20, 0),
            (9000, 4, 100, 30, 20), (9010, 4, 90, 30, 30)]  # away 10-0 at Q4 1:30 -> excluded
    r = s7_runs(pbp(rows), run_sizes=(8, 10))
    assert sorted(zip(r.running_team, r.threshold)) == [("home", 8), ("home", 10)]


def test_s6_first_trigger_and_windows():
    rows = [(0, 1, 720, 0, 0), (100, 1, 600, 0, 10), (200, 1, 500, 4, 10),
            (300, 2, 400, 4, 16), (400, 3, 700, 4, 30)]
    c = s6_candidates(pbp(rows), deficits=(10,))
    home = c[c.team == "home"].iloc[0]
    assert home.trigger_utc == T0 + pd.Timedelta(seconds=100)
    # trails by >=10 from 100 s until the 200 s basket, then again from 300 s; Q3 is out of scope
    assert home.price_windows == [(T0 + pd.Timedelta(seconds=100), T0 + pd.Timedelta(seconds=200)),
                                  (T0 + pd.Timedelta(seconds=300), T0 + pd.Timedelta(seconds=400))]
    assert (c.team == "away").sum() == 0


def test_first_price_in_windows():
    prices = pd.DataFrame({"utc_ts": T0 + pd.to_timedelta([50, 150, 350], unit="s"), "p": [1, 2, 3]})
    w = [(T0 + pd.Timedelta(seconds=100), T0 + pd.Timedelta(seconds=120)),
         (T0 + pd.Timedelta(seconds=300), T0 + pd.Timedelta(seconds=400))]
    assert first_price_in_windows(prices, w).p == 3
    assert first_price_in_windows(prices, w[:1]) is None
