# Phase 0: Data Feasibility Gate

**Status: BLOCKED. No GO/NO-GO yet.** I have no evidence either way because the session
couldn't reach any of the data sources.

## What blocked it
- This cloud environment's network policy refused these hosts (proxy `403` on CONNECT):
  `cdn.nba.com`, `stats.nba.com`, `api.the-odds-api.com`, `api.sportsgameodds.com`, `api.oddspapi.io`.
- No `ODDS_API_KEY` is set. Historical odds need a **paid** Odds API plan.
- I have **not** pulled any data and **no results are fabricated**. Everything below comes from
  documentation, and the open items have to be checked against a live call.

## 1. Live odds history (The Odds API, documented and not yet verified)
| Item | Documented | Still to verify with the probe |
|---|---|---|
| Snapshot interval | 10 min from Jun 2020; **5 min since Sep 2022** (featured markets: h2h/spreads/totals) | Actual gaps on in-play snapshots |
| In-play odds in historical snapshots | **Not stated clearly in the docs.** This is the key unknown. | Does an event still show up, with moving lines, after `commence_time`? |
| Query semantics | Returns the closest snapshot **at or before** `date`, plus `previous_timestamp`/`next_timestamp` | — |
| Cost | **10 credits × regions × markets** per call | `x-requests-used` header |
| Pinnacle | Listed under the `eu` region | Whether Pinnacle has in-play NBA lines in history |

**Credit estimate for 3 seasons** (`python -m phase0.run_probe --estimate-only`):
- One sport-wide historical call returns every NBA game in progress at that moment, so cost
  scales with **game-window wall-clock**, not with the number of games.
- Assumptions: `us` + `eu` regions, `spreads,totals`, which comes to **40 credits/call**. 5-min
  snapshots across each game day's window (first tip to last final), about 210–235 game days per
  season including playoffs.
- **About 2.0M–3.0M credits for 3 seasons.** Dropping `eu` halves that, but loses Pinnacle.
  Dropping `totals` also halves it, but the total-points split needs at least the pre-game total.
- The single-game probe costs **about 1,200 credits**.
- Per-event `/historical/.../events/{id}/odds` calls cost the same per call but cover only one
  game, so they're strictly worse here.

**Fallbacks** (both unverified, and both hosts are blocked here):
- **SportsGameOdds:** markets itself as having historical live odds. Interval and credit model
  need checking.
- **OddsPapi:** advertises historical odds with many books, including Pinnacle. Need to check
  in-play depth and granularity.

## 2. Play-by-play with wall-clock time
- Primary: `cdn.nba.com/static/json/liveData/playbyplay/playbyplay_{gameId}.json`. Each action
  is expected to carry `period`, `clock` (ISO duration), `scoreHome`/`scoreAway` and
  **`timeActual`** (UTC). hoopR exposes this as `time_actual`, which corroborates it.
  Still to verify: the field is populated for every action, and the files exist for 2023-24.
- Fallback: `nba_api` PlayByPlayV3 (stats.nba.com) has game clock but **no wall-clock
  timestamp**. Wall time would have to be interpolated, which is weak for S7's 5-min window.

## 3. Alignment test (code ready, not yet run)
- `phase0/align.py` does an as-of join: each odds row gets the latest PBP event at or before the
  book's `last_update`, falling back to snapshot time. Rows go stale after 180 s, and
  pre-tip/post-final rows are excluded. This logic is unit-tested in `tests/test_align.py`.
- `phase0/run_probe.py --game-id <id> --yes` walks every snapshot from tip to final for one game.
  It writes `data/phase0/aligned_<id>.csv` and a summary with:
  - median and max snapshot gap
  - books seen, and in-play rows per book
  - whether Pinnacle has in-play lines
  - the correlation of the home live spread with the home margin, which should be strongly negative
  - the join success rate

## Decision rule I'll apply once the probe runs
- **GO** if all of these hold:
  - in-play snapshots exist
  - the median interval is ≤ 10 min
  - at least one consistent book (ideally Pinnacle) is in-play in most snapshots
  - `timeActual` is present
  - spread-vs-margin correlation ≤ −0.8
- **NO-GO / alternatives** if in-play isn't in the history, or the interval is > 10 min:
  - switch to SportsGameOdds or OddsPapi history
  - or record live odds going forward (a 2025-26+ prospective sample only)
  - or narrow S6 to halftime lines, if a period/halftime market history exists
- **Methodological caveat even on GO:** 5-min snapshots mean S7 bets go in up to 5 min after a
  run. That's a fair test of "the line you could actually get", but it's coarse. Books also
  suspend markets during runs, so missing in-play rows around runs should be expected and reported.

## To unblock
1. Allow these hosts in the environment's network settings:
   `cdn.nba.com`, `api.the-odds-api.com`, plus `api.sportsgameodds.com` and `api.oddspapi.io` for
   the fallbacks. See https://code.claude.com/docs/en/cloud-environments#network-access.
2. Provide `ODDS_API_KEY` (a paid plan) as an environment secret.
3. Choose a sample game ID, then run:
   `pip install -r requirements.txt && python -m phase0.run_probe --game-id <id> --yes`
