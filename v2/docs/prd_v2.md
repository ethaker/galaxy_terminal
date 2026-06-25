# Galaxy Terminal — Prediction Market TG Bot PRD v2

---

## Working Principles
- **Always treat the existing codebase as the baseline** — before building anything new, review what's already implemented and build on top of it rather than from scratch

---

## Overview
- TG bot that keeps the Galaxy S&T PM desk sales team informed about how the markets they care about are changing
- Push-based: structured daily digest + real-time alerts surface relevant market activity without requiring the team to go looking
- **Core stack unchanged: AWS Lambda + Telegram Bot API + Polymarket Gamma/CLOB APIs + S3 for config storage**
- v1 scope is Polymarket only

---

## Problem
- Current output surfaces too many low-relevance markets — users fatigue and stop reading
- Tag-based filtering is unreliable; the market corpus is too broad and unfiltered
- Output has no hierarchy — every line carries equal weight, nothing stands out
- Event-driven alerts are not currently functioning

---

## Solution
- Maintain a **curated whitelist** of markets the desk actively tracks, stored in S3 and read by Lambda on every run
- Whitelist managed via TG slash commands (`/add [url]`, `/remove [slug]`); S3 as the underlying config store
- Surface markets where activity is meaningful — possible approaches include:
  - **Activity score** (`vol_24h / OI`) — ranks markets by how active they are relative to their size
  - **Absolute price change** — `oneDayPriceChange` already returned by Gamma, no extra API calls
  - **Smarter tag filtering** — more disciplined use of Gamma tag params rather than hardcoded IDs
  - These approaches can be combined; activity score + whitelist is the current preference but not the only path
- **Stack stays as-is. All changes are logic and config, not infrastructure.**

---

## Scope

**P0 — need to have**
- S3 config file for whitelist storage; Lambda reads it on every run
- Improved output formatting: clean headers, subheaders, italicized stats, clear price, direct link per market
- Date-grouped digest structure for maximum legibility
- TG slash commands (`/add [url]`, `/remove [slug]`) via webhook (API Gateway + Lambda)

**P1 — high priority**
- Event-driven pings (diagnose and fix current non-functioning implementation)
- Price movement alerts in digest output

**P2 — medium priority**
- Kalshi integration (see kalshi_prd.md)

**P3 — low priority**
- Auto-expiry: drop markets from active tracking when `closed == true` or past `endDate`
- Activity score (`vol_24h / OI`) — rank and filter whitelist by relative activity
- Z-score / volatility normalization
- Tiered core/watch whitelist

---

## Plan

**P0 — ✅ Complete**
1. ✅ Rebuild output formatting — date-grouped, clean headers, italicized stats, price + link
2. ~~Deploy and validate formatting in test channel~~ *(used existing TG group)*
3. ✅ S3 config setup — `galaxy-terminal-config` bucket, `whitelist.json`, Lambda reads on each invocation
4. ✅ TG slash commands — `/add`, `/remove`, `/list` via API Gateway + `galaxy-terminal-webhook` Lambda
5. ✅ EventBridge schedules — digest fires daily at 8:15am and 4:00pm ET

**P1 — In planning**
- Event-driven price movement pings — rewrite from scratch
- Add price movement to digest output
- Activity score (`vol_24h / OI`) — rank and filter whitelist by relative activity

---

## Implementation

**P0 — ✅ Complete**
- Formatting: date-grouped headers, italicized stats (`Yes %`, `24h vol`, `OI`), direct link — MarkdownV2
- S3: `galaxy-terminal-config` bucket, `whitelist.json` as `[{slug, condition_id, title, added_date}]`
- Lambda `galaxy-terminal-digest`: reads S3 whitelist, fetches from Gamma `/events`, sends digest
- Lambda `galaxy-terminal-webhook`: handles `/add`, `/remove`, `/list` commands; strips `@botname` suffix
- API Gateway: `yehr1c1bt5`, `/webhook` POST → `galaxy-terminal-webhook`
- TG webhook registered; bot commands registered in Telegram
- EventBridge: `galaxy-terminal-digest-am` (12:15 UTC) and `galaxy-terminal-digest-pm` (20:00 UTC)
- IAM role: `glxy-pmtgbot-lambda-role` (AWSLambdaBasicExecutionRole + AmazonS3ReadOnlyAccess + AmazonAPIGatewayInvokeFullAccess)
- OI fixed: pulling from event-level `openInterest`, not market-level `liquidity`
- Price fixed: using `lastTradePrice` from Gamma, not CLOB `/price` endpoint

**P1**
- Event-driven pings rewritten from scratch — separate Lambda `galaxy-terminal-pings`, runs every 1 minute via EventBridge
- S3 gains a second file `prices.json` — stores last known `lastTradePrice` per condition ID, written after every ping run
- Ping logic: read whitelist → fetch current prices from Gamma → compare against `prices.json` → alert if threshold crossed → write new prices to S3
- Volume-tiered thresholds (carried over from original PRD):
  - $100k–$1M lifetime vol → alert if move > 3%
  - $1M–$10M → alert if move > 2.5%
  - $10M+ → alert if move > 1.25%
- S3 structure: `galaxy-terminal-config/whitelist.json` + `galaxy-terminal-config/prices.json`
- Price movement field added to digest: `oneDayPriceChange` from Gamma, already fetched — no extra API calls
- Activity score (`vol_24h / OI`) computed per market on each run — whitelist sorted by score, low-activity markets suppressed

**P2**
- Activity score (`vol_24h / OI`) computed from Gamma `/events` fields already fetched — no new API calls
- Auto-expiry: on each run, skip whitelist entries where `endDate` has passed or `closed == true`
- Kalshi: evaluate API surface and integration lift

**P3**
- Z-score and tiered whitelist revisit once corpus is stable

---

## Flags on Status Quo Codebase
- `open_interest` is incorrectly pulling `liquidity` from Gamma — these are different fields; OI should use `openInterest`
- `clobTokenIds` is returned from Gamma as a string `"[id1, id2]"` rather than a proper array — if Gamma changes formatting even slightly, the parser breaks silently
- CLOB `/price` endpoint is returning 404 — `lastTradePrice` from Gamma is already fetched and sufficient for the digest
- `mvmt_level` is a placeholder (`...`) — z-score not implemented
- Telegram credentials (bot token, chat ID) are hardcoded in source
- Event-driven pings code has multiple crashes before any alert fires:
  - `sorted_contracts` on line 318 sorts a set of `Contract` objects as if they were tuples — throws `TypeError`
  - CLOB `/prices-history` returns empty for most markets — hits `raise ValueError` on line 297 every run
  - `format_alert` unpacks `(key, contract)` tuples but iterates plain `Contract` objects by that point
  - `html` module used in `format_alert` but never imported
