"""S6/S7 trigger detection from play-by-play alone (run BEFORE fetching any prices).

Every trigger carries the UTC wall-clock window in which a price must be found. Prices are
then fetched only for games that have a trigger, then joined (see align.py)."""
import pandas as pd

REG_PERIOD_SEC, OT_PERIOD_SEC = 720, 300


def elapsed_game_sec(period, clock_sec):
    """Continuous game time: 0 at tip, 2880 at the end of regulation."""
    p = pd.Series(period).astype(int)
    before = (p.clip(upper=5) - 1) * REG_PERIOD_SEC + (p - 5).clip(lower=0) * OT_PERIOD_SEC
    length = p.map(lambda x: REG_PERIOD_SEC if x <= 4 else OT_PERIOD_SEC)
    return before + length - pd.Series(clock_sec)


def _scoring(pbp):
    """One row per event that changed the total score."""
    s = pbp.sort_values(["utc_ts", "action_number"]).reset_index(drop=True)
    total = s["score_home"] + s["score_away"]
    s = s[total.diff().fillna(total) > 0].copy()
    s["elapsed"] = elapsed_game_sec(s["period"].values, s["clock_sec"].values).values
    return s.reset_index(drop=True)


def s6_candidates(pbp, deficits=(8, 10, 12), periods=(1, 2)):
    """For each team and deficit D: first moment in Q1-Q2 the team trails by >= D, plus every
    UTC interval during which it keeps trailing by >= D (S6 bets at the first price observed
    inside one of those intervals). Favorite status (closing spread <= -4) is applied later,
    once the pre-game line is known, so this is a superset."""
    p = pbp.sort_values(["utc_ts", "action_number"]).reset_index(drop=True)
    in_window = p["period"].isin(periods)
    nxt_ts = p["utc_ts"].shift(-1)
    rows = []
    for team, sign in (("home", 1), ("away", -1)):
        deficit = -sign * p["margin_home"]
        for d in deficits:
            hit = in_window & (deficit >= d)
            if not hit.any():
                continue
            block = (hit != hit.shift()).cumsum()
            intervals = [(g["utc_ts"].iloc[0], nxt_ts.loc[g.index[-1]] if pd.notna(nxt_ts.loc[g.index[-1]])
                          else g["utc_ts"].iloc[-1]) for _, g in p[hit].groupby(block[hit])]
            first = p[hit].iloc[0]
            rows.append({"strategy": "S6", "team": team, "threshold": d,
                         "trigger_utc": first["utc_ts"], "period": int(first["period"]),
                         "clock_sec": first["clock_sec"], "margin_home": int(first["margin_home"]),
                         "price_windows": intervals})
    return pd.DataFrame(rows)


def s7_runs(pbp, run_sizes=(8, 10, 12), max_clock_sec=180, max_lag_sec=300,
            exclude_late_sec=120):
    """Runs: within <= max_clock_sec of game clock, one team outscores the other by >= N
    (net, so 12-2 counts as 10). The run 'ends' (and the trigger fires) at the scoring event
    where it first qualifies, which avoids look-ahead. One trigger per team per N. The bet goes
    AGAINST the running team at the first price in [trigger_utc, trigger_utc + max_lag_sec].
    Triggers in period >= 4 with < exclude_late_sec on the clock are dropped (OT included)."""
    s = _scoring(pbp)
    m = s["margin_home"].to_numpy()
    el = s["elapsed"].to_numpy()
    # margin just before each scoring event
    prev = pd.Series(m).shift(1, fill_value=0).to_numpy()
    rows = []
    for n in run_sizes:
        done = set()
        for j in range(len(s)):
            late = s.at[j, "period"] >= 4 and s.at[j, "clock_sec"] < exclude_late_sec
            if late:
                continue
            i = j
            best = {"home": 0, "away": 0}
            while i >= 0 and el[j] - el[i] <= max_clock_sec:
                delta = m[j] - prev[i]
                best["home"] = max(best["home"], delta)
                best["away"] = max(best["away"], -delta)
                i -= 1
            for team in ("home", "away"):
                if team not in done and best[team] >= n:
                    done.add(team)
                    t = s.at[j, "utc_ts"]
                    rows.append({"strategy": "S7", "running_team": team,
                                 "bet_team": "away" if team == "home" else "home",
                                 "threshold": n, "trigger_utc": t, "period": int(s.at[j, "period"]),
                                 "clock_sec": s.at[j, "clock_sec"],
                                 "margin_home": int(m[j]), "run_net": int(best[team]),
                                 "price_windows": [(t, t + pd.Timedelta(seconds=max_lag_sec))]})
    return pd.DataFrame(rows)


def first_price_in_windows(prices, windows, ts_col="utc_ts"):
    """First price row whose timestamp falls in any (start, end) window, or None."""
    ps = prices.sort_values(ts_col)
    for start, end in windows:
        hit = ps[(ps[ts_col] >= start) & (ps[ts_col] <= end)]
        if len(hit):
            return hit.iloc[0]
    return None
