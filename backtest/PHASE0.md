# Phase 0: Data Feasibility Gate (rev 2: $0 budget)

**Status: BLOCKED. No GO/NO-GO yet.** No data has been pulled, and nothing below is a measured result.

## Why it's blocked
- The environment's network policy still refuses `cdn.nba.com`, `api.elections.kalshi.com` and
  `api.oddspapi.io` (proxy 403 on CONNECT). The host allowlist change hasn't reached this session
  yet. A new session may be needed after it's saved.
- `ODDSPAPI_KEY` isn't present in the environment.

## What's ready
All of these modules are in `phase0/`, with 18 unit tests in `tests/`.

| Step | Module | What it does |
|---|---|---|
| PBP | `pbp.py` | nba.com CDN PBP plus schedule lookup by date and tricodes. Uses `timeActual` as UTC. |
| Triggers first | `triggers.py` | S6 candidates and S7 runs from PBP only. Each trigger gets the UTC window in which a price must be found. |
| Kalshi | `kalshi.py` | Public client: `/historical/cutoff`, NBA series discovery (`KXNBA*`), events, markets, trades, 1-min candlesticks. Falls back from live to `/historical/*` routes. Computes in-play liquidity stats. |
| OddsPapi | `oddspapi.py` | `/historical-odds` (≤3 books), a schema-agnostic snapshot flattener, quota-header capture, and in-play counts per book. |
| Join | `align.py` | Backward as-of join of any price stream to PBP state. Flags `stale` but doesn't drop stale rows, since the score is still correct at halftime and during timeouts. |
| Runner | `run_probe.py` | Runs one game end to end and writes `data/phase0/<gameId>/{triggers.csv, kalshi_trades_aligned.csv, oddspapi_aligned.csv, summary.json}`. |

Run:
`python -m phase0.run_probe --date 2026-10-23 --away HOU --home SAS`.

OddsPapi request cost: 1 `/historical-odds` call, plus 2 lookup calls (`/sports`, `/fixtures`)
unless `--fixture-id` is passed.

## Design change (implemented)
PBP → S6/S7 triggers → prices fetched only inside trigger windows.
- Kalshi is the primary backtest dataset.
- OddsPapi is the sportsbook validation subset, fetched only for triggering games.
- S6's favorite filter (closing spread ≤ −4) needs a pre-game line. `triggers.py` therefore emits
  a superset (any team trailing by ≥8 in Q1–Q2), and the favorite filter is applied once the
  pre-game line is known.

## Rule interpretations: please confirm (fixed before any data is seen)
1. **S7 "run ends":** the trigger fires at the scoring event where the net run first reaches N
   within ≤180 s of game clock. Waiting for the opponent's next basket would be look-ahead and
   would inflate run sizes.
2. **S7 Q4 exclusion:** also applies to OT with under 2:00 left (same endgame-fouling logic).
3. **S7 runs across a period break:** these count, using continuous elapsed game clock.
4. **S6 "any snapshot":** with Kalshi, a "snapshot" is a trade. The bet is the first trade while
   the deficit is still ≥ D in Q1–Q2.

## Documented facts and risks (from docs and third-party guides, not yet verified)
- **Kalshi coverage is the critical risk.**
  - Kalshi sports contracts launched in 2025. NBA game markets very likely don't exist for
    **2023-24** and may only cover part of **2024-25**.
  - Spread and total ladders show up in March–June 2026 data. Their start date is unknown, and
    they may not exist before 2025-26.
  - The probe counts `KXNBAGAME` events per season to settle this.
  - If confirmed, the TRAIN/HOLDOUT seasons can't stay as specified. That's your call: options
    are below.
- **Kalshi spread ≠ sportsbook spread.** Kalshi spreads are a ladder of binary "wins by over
  X.5" contracts, priced as probabilities, with no −110 vig. Grading uses the actual contract price.
- **OddsPapi history reportedly starts around January 2026.** If true, it can only validate
  2025-26 (the holdout) and later, never the train seasons.
- **Free OddsPapi quota:** marketing says 250 requests. Whether that's monthly is unverified,
  and the probe reads it from response headers.
- **Pinnacle in-play NBA depth** is known to be limited, so the probe counts in-play snapshots per book.
- **Sample game choice:** a completed **2026-27** game (Oct 23 2026, HOU @ SAS, which Kalshi lists
  as settled) keeps the 2025-26 holdout untouched. If OddsPapi only keeps recent history, this
  also gives it the best chance of having data.

## GO criteria (applied when the probe runs)
- **PBP:** `timeActual` present on every action and monotonic.
- **Kalshi:**
  - `KXNBAGAME` has in-play trades with a median gap of ≤ 60 s.
  - The home-win price vs. home margin correlation is ≥ +0.8.
  - Spread and total ladders exist; liquidity is reported either way.
  - Seasons with coverage give enough games for a train set (n ≥ 200 bets per variation is
    unlikely with a single season).
- **OddsPapi:** in-play price changes appear after tip for at least one book. This is a bonus for
  validation and doesn't block GO.

## If coverage is short: options (your decision, not mine)
- **A:** TRAIN = 2024-25 (partial) + 2025-26 first half, HOLDOUT = 2025-26 second half, then
  2026-27 to date.
- **B:** TRAIN = 2025-26, HOLDOUT = 2026-27 as it accrues (prospective).
- **C:** Moneyline-only S6/S7 on Kalshi wherever spreads are missing. This changes the bet type,
  so it would need re-registering.
