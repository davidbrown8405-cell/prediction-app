import pandas as pd

from phase0.kalshi import candles_to_frame, event_suffix, liquidity_summary, trades_to_frame
from phase0.oddspapi import flatten_snapshots, inplay_summary, quota_headers


def test_event_suffix_uses_eastern_date():
    # 00:30 UTC on the 24th is still the 23rd in New York
    assert event_suffix(pd.Timestamp("2026-10-24T00:30:00Z"), "HOU", "SAS") == "26OCT23HOUSAS"


def test_trades_cents_and_dollars():
    df = trades_to_frame([{"created_time": "2026-10-24T01:00:05Z", "yes_price": 62, "count": 3},
                          {"created_time": "2026-10-24T01:00:01Z", "yes_price_dollars": "0.6100",
                           "count_fp": "2.00"}], "T")
    assert df["yes_price"].tolist() == [0.61, 0.62] and df["count"].tolist() == [2.0, 3.0]


def test_liquidity_summary_counts_inplay_only():
    t = trades_to_frame([{"created_time": f"2026-10-24T01:0{i}:00Z", "yes_price": 50, "count": 1}
                         for i in range(5)], "T")
    c = candles_to_frame([{"end_period_ts": 1792803660, "price": {"close": 50},
                           "yes_bid": {"close": 49}, "yes_ask": {"close": 52}, "volume": 4}], "T")
    s = liquidity_summary(t, c, pd.Timestamp("2026-10-24T01:01:00Z"), pd.Timestamp("2026-10-24T01:05:00Z"))
    assert s["inplay_trades"] == 4 and s["median_gap_sec"] == 60.0 and s["trades_per_min"] == 1.0


def test_flatten_oddspapi_nested_snapshots():
    body = {"bookmakers": {"pinnacle": {"markets": {"111": {"outcomes": {"1": {"players": {"0": [
        {"createdAt": "2026-10-24T00:50:00Z", "price": 1.9, "active": True},
        {"createdAt": "2026-10-24T01:20:00Z", "price": 2.4, "active": True}]}}}}}}}}
    df = flatten_snapshots(body)
    assert df["book"].unique().tolist() == ["pinnacle"] and df["price"].tolist() == [1.9, 2.4]
    s = inplay_summary(df, pd.Timestamp("2026-10-24T01:00:00Z"), pd.Timestamp("2026-10-24T03:30:00Z"))
    assert s["pinnacle"]["inplay_snapshots"] == 1


def test_quota_headers_filter():
    h = {"X-RateLimit-Remaining": "240", "Content-Type": "json", "x-requests-limit": "250"}
    assert quota_headers(h) == {"X-RateLimit-Remaining": "240", "x-requests-limit": "250"}


def test_season_of_event_ticker():
    from phase0.run_probe import season_of
    assert season_of("KXNBAGAME-25JAN15LALBOS") == "2024-25"
    assert season_of("KXNBAGAME-26OCT23HOUSAS") == "2026-27"
