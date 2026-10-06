---
name: toss-api-skill
description: Operate the user's local beginner chart assistant from chat, including symbol, timeframe, visible period, observation date and automatic refresh, and explain the exact observation evidence returned by the app. Use for requests to control or read this chart assistant.
---

# Toss API chart control for Hermes

For offline low-entry analysis, use `low` below and skip tab/server discovery.

Invoke as `/toss-api-skill <request>`. Run the helper on the same computer as the chart server, using the absolute skill-directory path supplied by Hermes. If the terminal runs inside a container or another host, localhost points to that environment: report the connection mismatch instead of exposing the server publicly.

Use `scripts/chartctl.py` relative to this skill folder. It sends commands to an already running integrated chart app and waits for the browser's actual result. Python standard library only; browser-independent. Default URL is `http://127.0.0.1:8734`; override with `--url` or `CHART_ASSISTANT_URL` if the user uses another port.

For on-screen commands, first use `python3 "${HERMES_SKILL_DIR}/scripts/chartctl.py" tabs` to identify connected charts. If one tab is active it is selected automatically. For multiple tabs, use the user's intended symbol/tab; if still ambiguous ask which one. Pass `--tab ID` before the subcommand. A stale snapshot is not a current observation; use `inspect` for a fresh acknowledgement. An empty list means the updated app/browser tab must be opened or refreshed.

```bash
python3 "${HERMES_SKILL_DIR}/scripts/chartctl.py" view --symbol 005930.KS --tf D --period 6M
python3 "${HERMES_SKILL_DIR}/scripts/chartctl.py" view --as-of 2026-09-04
python3 "${HERMES_SKILL_DIR}/scripts/chartctl.py" view --as-of latest
python3 "${HERMES_SKILL_DIR}/scripts/chartctl.py" vp --symbol 005930.KS
python3 "${HERMES_SKILL_DIR}/scripts/chartctl.py" vp --symbol 005930.KS --as-of 2026-09-04
python3 "${HERMES_SKILL_DIR}/scripts/chartctl.py" inspect
python3 "${HERMES_SKILL_DIR}/scripts/chartctl.py" auto off
python3 "${HERMES_SKILL_DIR}/scripts/chartctl.py" result COMMAND_ID
```

`vp` computes the volume profile without a browser tab: it fetches candles from the local server (`/api/lookup`) and runs the same `results/dashboard/volume-profile.js` (`VolumeProfile.build`) through node. The JS is resolved from the app tree, or from the server's own static files for installed skill copies. Output envelope: `symbol`, `asOf`, `index`, `source`, `jsOrigin`, `volumeProfile` (same contract as the snapshot field, `null` when fewer than 10 valid candles).

Translate Korean names using the current tab snapshots or the app's `/api/search?q=<URL-encoded name>` response (official Toss catalog; includes KOSDAQ); common examples are 삼성전자 `005930.KS`, 애플 `AAPL`. Do not guess unfamiliar tickers. Timeframes: `D` 일봉, `W` 주봉, `H4` 4시간봉, `M` 월봉(장기 추세 확인용, 수익 보장 아님). Periods: `1M`, `3M`, `6M`, `1Y`, `ALL`. Period changes only the viewport, preserving the observation date. Selecting a different symbol/timeframe resets to latest unless an exact `--as-of` is supplied. Date selection supports exact daily/weekly bar dates and month-end labels (`YYYY-MM-DD`) for `M`; a missing/nontrading date is rejected, never silently replaced. Use latest for H4; historical H4 date commands are not supported in this version. `vp` is daily-only and may differ from the on-screen monthly profile; say which basis each uses. Monthly bars aggregate adjusted daily OHLCV; the in-progress month is provisional and 60-month averages are usually unavailable (reported, never substituted).

Explain `result.observation` directly: `label`, `reason`, `next`, `evidence`, `observationAsOf`, `ruleVersion`, `currentBarProvisional`. Include the returned source, market timestamp and `lastError` when relevant. Chart signals are observations, not executed trades. Do not recompute the rules in prose, imply quote freshness from command completion, or claim a new realtime trade merely because a subscription is connected.

Success requires `status: done`. Failed commands may have partially changed the view; inspect the returned actual snapshot. Expired or interrupted acknowledgements are uncertain: inspect `result COMMAND_ID` and the tab before considering another command. Do not automatically replay mutations. For comparison, inspect each requested symbol sequentially, keep each result's date/source, and restore the original view afterward; never treat different dates as a same-time comparison.

The bridge has no order, account, arbitrary code or file execution commands. It does not need the Toss key; keep credentials in the existing server configuration. Scope is the local app. Do not send its key elsewhere or alter observation rules to satisfy a natural-language command.

Entry requests: use `entry.judgmentMode`, `entry.label`, `entry.reason`, `entry.basis` and `entry.observationBasis`. `live-snapshot` is a provisional OHLCV snapshot judgment, not synchronized tick data; `closed-confirmed` uses the last confirmed timeframe bar and excludes the next trading price. Report both dates when entry and chart observation differ. `historical` is comparison only; `blocked` withholds judgment. `observation.timeliness.realtimeReady` and `syncReason` diagnose tick synchronization only, not snapshot permission. Never invent a trade watermark or turn a satisfied setup into an order recommendation.

Entry UI: the snapshot now includes `entry`. Use its `label`, `reason`, `setup`, selected strategies/mode, signal age and chaseLimit. `setup` being satisfied does not override the final entry decision or timeliness. The 0.5 ATR default chase cap and 3-bar expiry are experimental display guards, not validated returns or recommended order prices. A/B/C/F comparisons reflect source signals at the same bar; AND/OR is not a backtest or independent confidence score (F includes C). Strategy controls are currently on-screen, not CLI arguments.

Volume profile (매물대): the snapshot includes `volumeProfile` computed by the same on-screen `VolumeProfile.build(candles, index)` function. It covers the full data period up to the observation date (not a recent-N-bars window). Fields: `version` (`vp-1`), `method` (`hlc3`), `binCount` (12, or 1 if flat), `from`/`to` (the date or time of the first bar and the last bar used in the calculation), `count` (candles used), `total` (total volume), `bins` (array of `{low, high, volume, share, peak}`). The price range is `bins[].low/high`. If fewer than 10 valid candles exist, `volumeProfile` is `null` — report insufficient data rather than guessing. Do not recompute the profile in prose; use the returned bins as-is.


P2 cached daily patterns (repository CLI, installation update required):

```bash
python3 scripts/chartctl.py patterns --symbol 005930.KS
python3 scripts/chartctl.py events list --symbol 005930.KS
python3 scripts/chartctl.py events show --id EVENT_ID
```

These commands read stored server results without a browser tab or provider collection. Both `sharedMarketCache` and `horizontalPatterns` must be enabled on the server. No cache means `not-collected`; use the existing lookup or an analysis job explicitly to collect. `events show` returns exactly the UI event basis snapshot, including OHLCV, fixed boundary, ATR, RVOL, rule version and revision. Report event date and source collection time separately. Initial backfill (`initial-history`) is historical evidence, not a notification issued at that historical time. An unfinished bar is provisional; cached reads cannot refresh it. `revised` preserves the original event and reports source correction; `failed` is price evidence, never a provider error. P2 supports stocks D only. Existing `inspect` includes the on-screen `patterns` view; A/B/C/F entry remains separate. No automatic orders or external notifications.


P3 cached daily Bull/Bear Flag (repository CLI, installation update required):

```bash
python3 scripts/chartctl.py patterns --symbol 005930.KS --kind flag
```

Requires `sharedMarketCache` and `flagPatterns`. This reads stored results without provider collection; default `--kind horizontal` retains P2. `inspect.flags` matches the selected on-screen date and pause state. Use returned geometry, trigger/invalidation prices, retracement, volume evidence and `ruleVersion=flag-d-v2`; do not infer a target or an order. Event snapshots preserve the original channel at confirmation, including source revisions.


P4 server monitor (repository CLI, installation update required):

```bash
python3 scripts/chartctl.py monitor status
python3 scripts/chartctl.py monitor start
python3 scripts/chartctl.py monitor pause
```

These commands need the local server, not a chart tab. Requires `serverMonitor`, shared collection and the selected pattern rules. Read status without starting monitoring. Start/pause only for a user request to monitor/pause; screen auto-refresh is a separate control. The app imports saved watchlists through a preview and retains localStorage. Supports stocks D, 20 symbols, 3 focus symbols; normal 5-minute/focus 30-second polling, official session close plus 30-minute confirmation. Report source date, last collection, pause/error, interruption and provisional eligibility. Never treat old 5-minute data as current entry permission. Events are pattern conditions; use `events show` for the immutable basis. No orders, external alerts or independent A/B/C/F decisions.


P5 cached daily triangles (repository CLI, installation update required):

```bash
python3 scripts/chartctl.py patterns --symbol 005930.KS --kind triangle
```

Requires shared collection and `trianglePatterns`. Reads stored results without provider collection. `inspect.triangles` matches the on-screen observation date and pause state. `ruleVersion=triangle-d-v2` covers ascending, descending and symmetrical triangles; shape does not determine breakout direction. Use `direction` and confirmed/pending status. Both up and down triggers are returned; retest/failure uses boundaries frozen at confirmation. `events show` preserves the original OHLCV, geometry and source revision. The apex uses an anchor date plus a fractional logical bar offset, not a predicted trading date or price target. Stocks D only. No orders or return claims. Default monitor presets gain triangle once when enabled; custom rules stay unchanged.


Recent window and auxiliary indicators:

Pattern/event lists now cover the latest source daily bar minus three calendar months, including the pattern's structure start (Flag pole / Triangle convergence). Chart zoom does not expand this range. Use `window.start/end`; an old source reference is not today's quote. Original events and snapshots remain readable by ID. `inspect.indicator` returns the selected RSI/ATR/volume basis and value from the existing timeframe frame. Report `basisTime`, `timeframe`, `provisional`, `sourcePaused`, `status` and `sourceFetchedAt`. Volume ratio includes the current bar in its 20-bar mean; pattern RVOL uses the previous 20 bars. Do not substitute missing values from another timeframe or turn RSI thresholds into an order. Indicator choice is on-screen; switching it does not collect source data.


Price overlays and MACD (repository UI; refresh required):

`inspect.priceIndicators` returns the selected SMA/EMA/WMA/Bollinger/Donchian overlay: `kind`, `basisTime`, `values`, `names`, `parameters`, `status`, `provisional`, `sourcePaused`, `sourceFetchedAt`, `calculationVersion` and `seedPolicy`. Values follow `names` order; SMA/EMA/WMA return four averages in periods order 20/60/120/200, whereas Bollinger and Donchian return three values upper/middle/lower. `partial-data` means that only some of the selected averages are ready. `inspect.indicator` adds `kind=macd`, `signalValue`, `histogramValue`, parameters 12/26/9 and calculation version. EMA20/60/120/200 and all MACD EMA seeds use the first complete period SMA; MACD needs 34 consecutive closes for all three components. Bollinger uses 20 closes and population standard deviation ×2. Missing closes restart warm-up; no other timeframe substitution. Choices are on-screen, consume cached frame candles and do not collect data. Historical selection masks subsequent plotted values. These are descriptive values, not new A/B/C/F rules, alerts, orders or performance claims. External installed skill copies are not updated by repository documentation edits.


2026-10-06 coin extension (supersedes the Flag/Triangle stocks-only scope above):

Flag and Triangle now support coins D and H4 using existing yfinance frames. Horizontal/manual levels and server monitoring remain stocks D. Use `patterns --symbol BTC-USD --tf H4 --kind triangle` and `events list --symbol BTC-USD --tf H4` (D/H4 filter optional). Source collection is not triggered by these reads. `flag-h4-v1`/`triangle-h4-v1` use separate result/event identities. H4 time fields are UTC epoch seconds; D fields are ISO dates. The calendar three-month window is based on the latest bar of the same timeframe. Keep source `fetchedAt` separate from event bar time. Only a source fetch after bar end +30min confirms a coin bar; pending and expired snapshots cannot emit confirmed events. Absence of a currently valid pattern is a valid result; never loosen detection to force one. UI event popups render that timeframe's original candles/geometry. External installed skill copies are not updated here.


2026-10-06 price/volume extension (repository UI):

WMA20/60/120/200 uses linear weights 1..N from oldest to newest within a complete window. Donchian20 includes the current bar high/low with upper/middle/lower; it differs from the prior-bar-only C/F strategy breakout levels. `inspect.indicator.kind=obv` returns cumulative signed volume, `unit=volume`, `seedTime` and `seedPolicy=first-bar-zero-stop-on-gap`. OBV starts at zero on the first loaded bar, adds/subtracts current volume on a higher/lower close and stays unchanged on equal closes. Missing or negative volume/invalid close breaks the cumulative chain; later values remain unavailable until source correction. Do not compare absolute OBV across source history lengths or timeframes. Local calculation version is technical-v3; volume/high/low corrections invalidate cache. Choices reuse chart series, have no new data requests and do not alter strategy/alert rules.


Latest entry review contract (2026-10-06): `entry.version=ENTRY-2026-10-06`; raw A/B/C/F rules and their common 60-bar readiness gate are unchanged. Original A/B crosses may remain under review for the next three bars, while A SMA20>SMA60 or B RSI>30 and the prior-10-bar low must hold continuously. Selected exits cancel review. Chase checks use the original anchor price/ATR; freshness and bar confirmation still gate the final decision. AND requires an original same-bar combination, and C/F need current raw entries. `matched` remains the current raw combination; `continuation`/`reviewMatched` describe review eligibility only. Use final `code=candidate`, not `rows.phase=tracking`, to identify entry review. Rows add readiness/missing and new/maintained/tracking/wait/exit/unavailable phases. UI groups C/F under one breakout choice; legacy model combinations remain supported. Four-MA parameters are periods=[20,60,120,200], periodBars=200; source SMA20/60 is preserved, longer SMA overlays are local. This does not place orders or prove profitability.


Current pattern contract (2026-10-06): D/H4 flag and triangle rules use v2. Channel fit/containment tolerance is 0.4 ATR and coverage >=70%; three consecutive full-wick departures beyond tolerance invalidate the structure. Triangle endpoint width <=75% of initial width, confirmed pivot contacts >=5 with >=2 per side; flag pole >=2.5 ATR, retracement <=61.8%, adjustment <=30 bars. Source confirmation, three calendar months and close crossing boundary +/-0.1 ATR remain required. More detections do not demonstrate profitability or a lower false-positive rate. Stored v1 snapshots remain immutable; current-version monitoring hides legacy duplicate history when a v2 result exists. Inspect.entry.rows still contains raw A/B/C/F results even though the UI comparison table has A/B/one selected breakout row. No new provider calls are introduced. Backend changes require restarting the existing server and refreshing the same browser. External installed skill copies are not updated.


Low-entry analysis (`low-entry-v1`, package copy; installed copies need a separate update):

```bash
python3 scripts/chartctl.py low --symbol PLTR --tf D --as-of 2026-08-04
python3 scripts/chartctl.py low --symbol BTC-USD --tf H4 --strategy H --max-atr 0.5
```

`low` reads the local SQLite candle cache with `mode=ro`, runs the shared JS engine and makes no API request. No browser/server startup is needed. Use `--input frame.json` for an explicit frame, `--cache file.sqlite3` for another cache, or `--project integrated-project-folder` when running an installed helper. Missing cached symbols fail; do not collect merely to force a result.

Report source `fetchedAt`, `observedThrough`, `confirmedThrough`, version and final `decision.code`. Latest means the latest stored snapshot, not a verified current quote. For a user explicitly requesting realtime analysis, use a fresh app acknowledgement and verify its timing instead of calling an old cache realtime. Historical results retain `code=historical` and `setupDecision`; do not turn a green historical setup into current entry advice. D and coin H4 are supported; H4 cutoff uses UTC epoch seconds.

R waits for support reclaim, a confirmed retest and rebound high crossing. H waits for a confirmed higher low and intervening high crossing. R/H use OR independently; same-time candidates choose H and do not merge prices. Original A/B/C/F rules are unchanged. Markers show pivot occurrence separately from confirmation. Volume/OBV/price response are supplemental; profit and actual absorption are unverified. The first signal candle can already be far above its trigger: report the initial-extension warning separately from the fixed subsequent chase cap. No orders or persistent alerts are created.

Browser `inspect.lowStructures` returns recent structures, the selected one, timing-gated decision, evidence and events. On-screen **전략군 → 저점 매수** enables the low-entry card/overlay; default remains the original family. Rule details and validation are consolidated in the project's `docs/FEATURES.md`, the low-entry section.
