---
name: chart-assistant
description: Control the user's local chart assistant, show chart and auxiliary indicator data in chat, explain entry judgments, read cached patterns/events, and analyze R/H low-entry structures offline. Use for requests to operate or analyze with this chart assistant.
---

# Chart assistant

Project: the cloned Stock-Newbby folder. Packaged skill: `skills/chart-assistant`. After edits, update the installed skill with `python3 tools/install-chart-skill.py --update`.

For analysis requests, include chart auxiliary data directly in the conversation, not only a prose conclusion or a link to the app. Read [references/chat-data.md](references/chat-data.md) for the compact indicator/level/volume-profile output and its date/source rules. Prefer the acknowledged snapshot or one already acquired frame; calculate missing auxiliary values with the app's shared JS modules without changing the selected chart indicators or collecting again for each value. Simple navigation requests do not need a full report.

Choose the execution mode before discovery:
- On-screen `view`/`inspect`/`auto`: needs the running server and its existing chart tab. Use one browser; reuse the user's tab.
- Cached `patterns`/`events`/`monitor`: needs the running server, no browser. Reads do not collect provider data; monitor start/pause changes server polling.
- `vp`: needs the running server and node, no browser; `/api/lookup` may collect candles.
- Offline `low`: needs node>=22, the project and saved candles, no server/browser. Skip tab discovery and pass `--project` when using the installed helper.

Use `scripts/chartctl.py` relative to this skill folder. On-screen commands send to the running integrated app and wait for its browser's actual result. The Python helper uses the standard library; `vp`/`low` also run node. Default URL is `http://127.0.0.1:8734`; override with `--url` or `CHART_ASSISTANT_URL` if the user uses another port.

For on-screen commands, first use `python3 scripts/chartctl.py tabs` to identify connected charts. If one tab is active it is selected automatically. For multiple tabs, use the user's intended symbol/tab; if still ambiguous ask which one. Pass `--tab ID` before the subcommand. A stale snapshot is not a current observation; use `inspect` for a fresh acknowledgement. An empty list means the updated app/browser tab must be opened or refreshed.

Commands:

```bash
python3 scripts/chartctl.py view --as-of 2026-09-04
python3 scripts/chartctl.py view --as-of latest
python3 scripts/chartctl.py vp --symbol 005930.KS
python3 scripts/chartctl.py vp --symbol 005930.KS --as-of 2026-09-04
python3 scripts/chartctl.py view --symbol 005930.KS --tf M --period ALL --as-of 2026-08-31
python3 scripts/chartctl.py inspect
python3 scripts/chartctl.py auto off
python3 scripts/chartctl.py result COMMAND_ID
```

`vp` computes the volume profile without a browser tab: it fetches candles from the local server (`/api/lookup`) and runs the same `results/dashboard/volume-profile.js` (`VolumeProfile.build`) through node. The JS is resolved from the app tree, or from the server's own static files for installed skill copies. Output envelope: `symbol`, `asOf`, `index`, `source`, `jsOrigin`, `volumeProfile` (same contract as the snapshot field, `null` when fewer than 10 valid candles). `vp` is daily-only: its profile may differ from the on-screen monthly profile; say which basis each uses.

Monthly (월봉, `--tf M`): long-term trend view, not a return forecast. Bars aggregate adjusted daily OHLCV (open first, high max, low min, close last, volume summed); the label is the month's last calendar day (`YYYY-MM-DD`), distinct from the actual last-session end. `--as-of` accepts only month-end labels. The in-progress month is provisional; closed-bar judgment falls back to the prior confirmed month and reports both via `entry.basis`/`entry.observationBasis`. About 35 bars fit in the daily window, so 60-month averages (A/F criteria) are usually unavailable and reported as such, never substituted.

Explain `result.observation` directly: `label`, `reason`, `next`, `evidence`, `observationAsOf`, `ruleVersion`, `currentBarProvisional`. Include the returned source, market timestamp and `lastError` when relevant. Chart signals are observations, not executed trades. Do not recompute the rules in prose, imply quote freshness from command completion, or claim a new realtime trade merely because a subscription is connected.

For browser bridge commands, success requires `status: done`; cached commands, `vp` and `low` return their own JSON contracts. Failed commands may have partially changed the view; inspect the returned actual snapshot. Expired or interrupted acknowledgements are uncertain: inspect `result COMMAND_ID` and the tab before considering another command. Do not automatically replay mutations. For comparison, inspect each requested symbol sequentially, keep each result's date/source, and restore the original view afterward; never treat different dates as a same-time comparison.

The bridge has no order, account, arbitrary code or file execution commands. It does not need the Toss key; keep credentials in the existing server configuration. Scope is the local app. Do not send its key elsewhere or alter observation rules to satisfy a natural-language command.

Entry requests: use `entry.judgmentMode`, `entry.label`, `entry.reason`, `entry.basis` and `entry.observationBasis`. `live-snapshot` is a provisional OHLCV snapshot judgment, not synchronized tick data; `closed-confirmed` uses the last confirmed timeframe bar and excludes the next trading price. Report both dates when entry and chart observation differ. `historical` is comparison only; `blocked` withholds judgment. `observation.timeliness.realtimeReady` and `syncReason` diagnose tick synchronization only, not snapshot permission. Never invent a trade watermark or turn a satisfied setup into an order recommendation.

Entry UI: the snapshot now includes `entry`. Use its `label`, `reason`, `setup`, selected strategies/mode, signal age and chaseLimit. `setup` being satisfied does not override the final entry decision or timeliness. The 0.5 ATR default chase cap and 3-bar expiry are experimental display guards, not validated returns or recommended order prices. For `entry.family=legacy`, raw A/B/C/F comparisons reflect signals at the same bar; UI groups C/F as one breakout choice. AND/OR is not a backtest or independent confidence score (F includes C). For `entry.family=low`, use the final R/H decision and selected strategies instead. `settingsId` identifies the settings, not confidence. `lowStructures.manual=true` means separately selected historical geometry; it does not replace the final entry judgment. On-screen strategy settings are not bridge CLI arguments; offline `low` independently accepts R/H selection and a chase cap.

Volume profile (매물대): the snapshot includes `volumeProfile` computed by the same on-screen `VolumeProfile.build(candles, index)` function. It covers the full data period up to the observation date (not a recent-N-bars window). Fields: `version` (`vp-1`), `method` (`hlc3`), `binCount` (12, or 1 if flat), `from`/`to` (the date or time of the first bar and the last bar used in the calculation), `count` (candles used), `total` (total volume), `bins` (array of `{low, high, volume, share, peak}`). The price range is `bins[].low/high`. If fewer than 10 valid candles exist, `volumeProfile` is `null` — report insufficient data rather than guessing. Do not recompute the profile in prose; use the returned bins as-is.


Cached horizontal patterns:

```bash
python3 scripts/chartctl.py patterns --symbol 005930.KS
python3 scripts/chartctl.py events list --symbol 005930.KS
python3 scripts/chartctl.py events show --id EVENT_ID
```

These commands read stored server results without a browser tab or provider collection. Both `sharedMarketCache` and `horizontalPatterns` must be enabled on the server. No cache means `not-collected`; use the existing lookup or an analysis job explicitly to collect. `events show` returns exactly the UI event basis snapshot, including OHLCV, fixed boundary, ATR, RVOL, rule version and revision. Report event date and source collection time separately. Initial backfill (`initial-history`) is historical evidence, not a notification issued at that historical time. An unfinished bar is provisional; cached reads cannot refresh it. `revised` preserves the original event and reports source correction; `failed` is price evidence, never a provider error. Horizontal patterns support stocks D only. Existing `inspect` includes the on-screen `patterns` view; A/B/C/F entry remains separate. No automatic orders or external notifications.


Cached Bull/Bear Flag:

```bash
python3 scripts/chartctl.py patterns --symbol 005930.KS --kind flag
```

Requires `sharedMarketCache` and `flagPatterns`. This reads stored results without provider collection; default `--kind horizontal` reads horizontal patterns. `inspect.flags` matches the selected on-screen date and pause state. Use returned geometry, trigger/invalidation prices, retracement, volume evidence and `ruleVersion=flag-d-v2` for D or `flag-h4-v3` for coin H4; do not infer a target or an order. Event snapshots preserve the original channel at confirmation, including source revisions.


Server monitor:

```bash
python3 scripts/chartctl.py monitor status
python3 scripts/chartctl.py monitor start
python3 scripts/chartctl.py monitor pause
```

These commands need the local server, not a chart tab. Server monitoring is daily pattern monitoring, separate from on-screen R/H low-entry evaluation. Requires `serverMonitor`, shared collection and the selected pattern rules. Read status without starting monitoring. Start/pause only for a user request to monitor/pause; screen auto-refresh is a separate control. The app imports saved watchlists through a preview and retains localStorage. Supports stocks D, 20 symbols, 3 focus symbols; normal 5-minute/focus 30-second polling, official session close plus 30-minute confirmation. Report source date, last collection, pause/error, interruption and provisional eligibility. Never treat old 5-minute data as current entry permission. Events are pattern conditions; use `events show` for the immutable basis. No orders, external alerts or independent A/B/C/F decisions.


Cached triangles:

```bash
python3 scripts/chartctl.py patterns --symbol 005930.KS --kind triangle
```

Requires shared collection and `trianglePatterns`. Reads stored results without provider collection. `inspect.triangles` matches the on-screen observation date and pause state. `ruleVersion=triangle-d-v2` (D) or `triangle-h4-v3` (coin H4) covers ascending, descending and symmetrical triangles; shape does not determine breakout direction. Use `direction` and confirmed/pending status. Both up and down triggers are returned; retest/failure uses boundaries frozen at confirmation. `events show` preserves the original OHLCV, geometry and source revision. The apex uses an anchor date plus a fractional logical bar offset, not a predicted trading date or price target. Stocks D and coins D/H4. No orders or return claims. Default monitor presets gain triangle once when enabled; custom rules stay unchanged.


Recent window and auxiliary indicators:

Pattern/event lists cover the latest source bar of the same timeframe minus three calendar months, including the pattern's structure start (Flag pole / Triangle convergence). Chart zoom does not expand this range. Use `window.start/end`; an old source reference is not today's quote. Original events and snapshots remain readable by ID. `inspect.indicator` returns the selected RSI/ATR/volume basis and value from the existing timeframe frame. Report `basisTime`, `timeframe`, `provisional`, `sourcePaused`, `status` and `sourceFetchedAt`. Volume ratio includes the current bar in its 20-bar mean; pattern RVOL uses the previous 20 bars. Do not substitute missing values from another timeframe or turn RSI thresholds into an order. Indicator choice is on-screen; switching it does not collect source data.


Price overlays and MACD:

`inspect.priceIndicators` returns the selected SMA/EMA/WMA/Bollinger/Donchian overlay: `kind`, `basisTime`, `values`, `names`, `parameters`, `status`, `provisional`, `sourcePaused`, `sourceFetchedAt`, `calculationVersion` and `seedPolicy`. Values follow `names` order; SMA/EMA/WMA return four averages in periods order 20/60/120/200, whereas Bollinger and Donchian return three values upper/middle/lower. `partial-data` means that only some of the selected averages are ready. `inspect.indicator` adds `kind=macd`, `signalValue`, `histogramValue`, parameters 12/26/9 and calculation version. EMA20/60/120/200 and all MACD EMA seeds use the first complete period SMA; MACD needs 34 consecutive closes for all three components. Bollinger uses 20 closes and population standard deviation ×2. Missing closes restart warm-up; no other timeframe substitution. Choices are on-screen, consume cached frame candles and do not collect data. Historical selection masks subsequent plotted values. These are descriptive values, not new A/B/C/F rules, alerts, orders or performance claims.


Coin Flag/Triangle:

Flag and Triangle support stocks D and coins D/H4; coins use existing yfinance frames. Horizontal/manual levels and server monitoring remain stocks D. Use `patterns --symbol BTC-USD --tf H4 --kind triangle` and `events list --symbol BTC-USD --tf H4` (D/H4 filter optional). Source collection is not triggered by these reads. `flag-h4-v3`/`triangle-h4-v3` use separate result/event identities. Missing H4 bars split contiguous segments and restart ATR/pivot/structure warm-up; do not connect a channel across the gap. Older snapshots retain their original rule version. H4 time fields are UTC epoch seconds; D fields are ISO dates. The calendar three-month window is based on the latest bar of the same timeframe. Keep source `fetchedAt` separate from event bar time. Only a source fetch after bar end +30min confirms a coin bar; pending and expired snapshots cannot emit confirmed events. Absence of a currently valid pattern is a valid result; never loosen detection to force one. UI event popups render that timeframe's original candles/geometry.


WMA, Donchian and OBV:

WMA20/60/120/200 uses linear weights 1..N from oldest to newest within a complete window. Donchian20 includes the current bar high/low with upper/middle/lower; it differs from the prior-bar-only C/F strategy breakout levels. `inspect.indicator.kind=obv` returns cumulative signed volume, `unit=volume`, `seedTime` and `seedPolicy=first-bar-zero-stop-on-gap`. OBV starts at zero on the first loaded bar, adds/subtracts current volume on a higher/lower close and stays unchanged on equal closes. Missing or negative volume/invalid close breaks the cumulative chain; later values remain unavailable until source correction. Do not compare absolute OBV across source history lengths or timeframes. Local calculation version is technical-v3; volume/high/low corrections invalidate cache. Choices reuse chart series, have no new data requests and do not alter strategy/alert rules.


Latest entry review contract (2026-10-06): `entry.version=ENTRY-2026-10-06`; raw A/B/C/F rules and their common 60-bar readiness gate are unchanged. Original A/B crosses may remain under review for the next three bars, while A SMA20>SMA60 or B RSI>30 and the prior-10-bar low must hold continuously. Selected exits cancel review. Chase checks use the original anchor price/ATR; freshness and bar confirmation still gate the final decision. AND requires an original same-bar combination, and C/F need current raw entries. `matched` remains the current raw combination; `continuation`/`reviewMatched` describe review eligibility only. Use final `code=candidate`, not `rows.phase=tracking`, to identify entry review. Rows add readiness/missing and new/maintained/tracking/wait/exit/unavailable phases. UI groups C/F under one breakout choice; legacy model combinations remain supported. Four-MA parameters are periods=[20,60,120,200], periodBars=200; source SMA20/60 is preserved, longer SMA overlays are local. This does not place orders or prove profitability.


Current pattern contract (2026-10-06): D flag/triangle rules use v2; H4 uses v3 for gap handling with the same v2 thresholds. Channel fit/containment tolerance is 0.4 ATR and coverage >=70%; three consecutive full-wick departures beyond tolerance invalidate the structure. Triangle endpoint width <=75% of initial width, confirmed pivot contacts >=5 with >=2 per side; flag pole >=2.5 ATR, retracement <=61.8%, adjustment <=30 bars. Source confirmation, three calendar months and close crossing boundary +/-0.1 ATR remain required. More detections do not demonstrate profitability or a lower false-positive rate. Stored v1/v2 snapshots remain immutable; current-version event lists suppress older duplicate history when a current result exists. Inspect.entry.rows still contains raw A/B/C/F results even though the UI comparison table has A/B/one selected breakout row. No new provider calls are introduced. Backend changes require restarting the existing server and refreshing the same browser.


Offline low-entry analysis (`low-entry-v1`):

```bash
python3 ~/.codex/skills/chart-assistant/scripts/chartctl.py low \
  --project '/path/to/Stock-Newbby' \
  --symbol PLTR --tf D --as-of 2026-08-04
# From the project, the packaged helper locates its project automatically:
python3 skills/chart-assistant/scripts/chartctl.py low --symbol BTC-USD --tf H4 --strategy H --max-atr 0.5
```

`low` reads the local SQLite candle cache with `mode=ro`, runs the shared JS engine and makes no API request. No browser/server startup is needed. Use `--input frame.json` for an explicit frame, `--cache file.sqlite3` for another cache, or `--project integrated-project-folder` when running an installed helper. Missing cached symbols fail; do not collect merely to force a result.

Output is a JSON array, not a browser acknowledgement. Report each result's source `fetchedAt`, `observedThrough`, `confirmedThrough`, version and final `decision.code`. Latest means the latest stored snapshot, not a verified current quote. For a user explicitly requesting realtime analysis, use a fresh app acknowledgement and verify its timing instead of calling an old cache realtime. Historical results retain `code=historical` and `setupDecision`; do not turn a green historical setup into current entry advice. D and coin H4 are supported; H4 cutoff uses UTC epoch seconds.

R waits for support reclaim, a confirmed retest and rebound high crossing. H waits for a confirmed higher low and intervening high crossing. R/H use OR independently; same-time candidates choose H and do not merge prices. Original A/B/C/F rules are unchanged. Markers show pivot occurrence separately from confirmation. Volume/OBV/price response are supplemental; profit and actual absorption are unverified. The first signal candle can already be far above its trigger: report the initial-extension warning separately from the fixed subsequent chase cap. No orders or persistent alerts are created.

Browser `inspect.lowStructures` returns recent structures, the selected one, timing-gated decision, evidence and events. On-screen **전략군 → 저점 매수** enables the low-entry card/overlay; default remains the original family. Rule details and validation are consolidated in the project's `docs/FEATURES.md`, the low-entry section.


Pattern timing: `inspect.patterns`/`flags`/`triangles` share the current/historical rule. Clicking the latest bar still means current view. A current unfinished snapshot is blocked after 90 seconds, automatic refresh OFF/hidden, or a lookup error. A past confirmed result is not invalidated by today's fetch error. Report the returned state and source date rather than inferring permission from chart color.


Stock H4 provider routing (2026-10-07): `/api/intraday` uses Toss adjusted 1-minute candles when Toss is configured, and yfinance 60-minute candles only when unconfigured. Coins/indices stay on yfinance. A Toss failure does not switch sources. Initial minute paging may return `queue-busy` while the same background collection continues; do not force/replay requests or label this as authentication failure. Frames carry `source`, `sourceInterval=1m`, `aggregation` and `history`. Toss minutes may include extended sessions, so H4 timestamps/values can differ from Yahoo regular-session frames. Preserve fetched/market times, confirmation/freshness guards and missing-indicator states. Stocks H4 pattern/R/H support remains unchanged (unsupported).
