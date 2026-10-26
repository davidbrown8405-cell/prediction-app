"""Kalshi public market data (no key). Prices are YES probabilities in [0, 1].

Settled markets older than Kalshi's historical cutoff move to /historical/* routes, and live
routes can return 200 with an empty list for them, so each fetch tries live then historical."""
import pandas as pd

from .http_cache import cached_get

MONTHS = "JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC".split()


class Kalshi:
    def __init__(self, base_url, min_interval=0.1):
        self.base, self.min_interval = base_url.rstrip("/"), min_interval

    def get(self, path, **params):
        body, _, _ = cached_get(f"{self.base}{path}", params=params or None,
                                min_interval=self.min_interval, allow_404=True)
        return body

    def paged(self, path, key, **params):
        out, cursor = [], None
        while True:
            body = self.get(path, **params, **({"cursor": cursor} if cursor else {})) or {}
            out += body.get(key) or []
            cursor = body.get("cursor")
            if not cursor:
                return out

    def cutoff(self):
        return self.get("/historical/cutoff")

    def nba_series(self, prefix="KXNBA"):
        series = self.paged("/series", "series", category="Sports")
        return [s for s in series if s.get("ticker", "").startswith(prefix)]

    def events(self, series_ticker, status=None):
        params = {"series_ticker": series_ticker, "limit": 200}
        if status:
            params["status"] = status
        return self.paged("/events", "events", **params)

    def markets(self, event_ticker):
        live = self.paged("/markets", "markets", event_ticker=event_ticker, limit=1000)
        return live or self.paged("/historical/markets", "markets", event_ticker=event_ticker, limit=1000)

    def trades(self, ticker, min_ts, max_ts):
        args = dict(ticker=ticker, min_ts=int(min_ts), max_ts=int(max_ts), limit=1000)
        return self.paged("/markets/trades", "trades", **args) or self.paged("/historical/trades", "trades", **args)

    def candles(self, series_ticker, ticker, start_ts, end_ts, interval_min=1):
        args = dict(start_ts=int(start_ts), end_ts=int(end_ts), period_interval=interval_min)
        body = self.get(f"/series/{series_ticker}/markets/{ticker}/candlesticks", **args) or {}
        if not body.get("candlesticks"):
            body = self.get(f"/historical/markets/{ticker}/candlesticks", **args) or {}
        return body.get("candlesticks") or []


def event_suffix(tip_utc, away, home):
    """Kalshi game event suffix, e.g. 26OCT23HOUSAS, keyed on the US/Eastern game date.
    Tricode mismatches between NBA and Kalshi (if any) surface as a missing event."""
    d = pd.Timestamp(tip_utc).tz_convert("America/New_York")
    return f"{d:%y}{MONTHS[d.month - 1]}{d:%d}{away}{home}"


def _dollars(row, name):
    """Kalshi gives either `<name>_dollars` (string, $) or `<name>` (int cents)."""
    if row.get(f"{name}_dollars") not in (None, ""):
        return float(row[f"{name}_dollars"])
    v = row.get(name)
    return None if v is None else v / 100


def trades_to_frame(trades, ticker):
    df = pd.DataFrame([{
        "ticker": ticker, "utc_ts": pd.Timestamp(t["created_time"]),
        "yes_price": _dollars(t, "yes_price"),
        "count": float(t.get("count_fp") or t.get("count") or 0),
        "taker_side": t.get("taker_side")} for t in trades])
    if df.empty:
        return pd.DataFrame(columns=["ticker", "utc_ts", "yes_price", "count", "taker_side"])
    df["utc_ts"] = pd.to_datetime(df["utc_ts"], utc=True)
    return df.sort_values("utc_ts").reset_index(drop=True)


def candles_to_frame(candles, ticker):
    def side(c, k, f):
        v = (c.get(k) or {})
        return _dollars(v, f)
    rows = [{"ticker": ticker,
             "utc_ts": pd.Timestamp(c["end_period_ts"], unit="s", tz="UTC"),
             "close": side(c, "price", "close"),
             "yes_bid": side(c, "yes_bid", "close"), "yes_ask": side(c, "yes_ask", "close"),
             "volume": float(c.get("volume_fp") or c.get("volume") or 0),
             "open_interest": float(c.get("open_interest_fp") or c.get("open_interest") or 0)}
            for c in candles]
    return pd.DataFrame(rows)


def market_strike(m):
    """Strike for spread/total ladders (e.g. 4.5 points), None for moneyline markets."""
    for k in ("floor_strike", "cap_strike"):
        if m.get(k) is not None:
            return float(m[k])
    return None


def liquidity_summary(trades, candles, tip, final):
    """In-play trade frequency and quote quality for one market."""
    t = trades[(trades["utc_ts"] >= tip) & (trades["utc_ts"] <= final)]
    c = candles[(candles["utc_ts"] >= tip) & (candles["utc_ts"] <= final)] if len(candles) else candles
    minutes = (final - tip).total_seconds() / 60
    gaps = t["utc_ts"].diff().dt.total_seconds().dropna()
    spread = (c["yes_ask"] - c["yes_bid"]) if len(c) else pd.Series(dtype=float)
    return {
        "inplay_trades": len(t), "inplay_contracts": float(t["count"].sum()),
        "trades_per_min": round(len(t) / minutes, 2) if minutes else None,
        "median_gap_sec": float(gaps.median()) if len(gaps) else None,
        "p90_gap_sec": float(gaps.quantile(0.9)) if len(gaps) else None,
        "minutes_with_trade_pct": round(100 * t["utc_ts"].dt.floor("min").nunique() / minutes, 1) if minutes else None,
        "median_bid_ask": float(spread.median()) if len(spread.dropna()) else None,
    }
