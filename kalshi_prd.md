# Kalshi Integration PRD

---

## Working Principles
- Same stack: existing Lambda functions extended, not duplicated
- Treat Kalshi as an additive data source — the existing Polymarket digest and pings architecture is the baseline
- Parity means: same whitelist management, same digest format, same price movement alerts

---

## What Kalshi Is
Kalshi is a CFTC-regulated US prediction market exchange. It overlaps heavily with Polymarket on macro, political, and economic markets — Fed rate cuts, tariffs, elections — with meaningful liquidity on many of the same events. It is not a crypto-native platform and has a distinct user base; Kalshi markets sometimes price differently from Polymarket for the same underlying event, which is intrinsically interesting for an S&T desk.

---

## API Overview (from live inspection)

**Base URL:** `https://external-api.kalshi.com/trade-api/v2`

**Key endpoints:**
- `GET /events?limit=N&with_nested_markets=true` — returns event objects with nested market arrays
- `GET /markets?event_ticker=KXINFL` — returns markets for an event
- `GET /events/{event_ticker}` — single event lookup

**Market object fields (relevant):**
| Field | Type | Notes |
|---|---|---|
| `ticker` | string | Primary market identifier, e.g. `KXINFL-26-B3PT5` |
| `event_ticker` | string | Parent event, e.g. `KXINFL-26` |
| `title` | string | Market question |
| `last_price_dollars` | string | Current price as decimal, e.g. `"0.7900"` = 79% Yes |
| `previous_price_dollars` | string | Prior close price — enables 24h change without extra calls |
| `yes_bid_dollars` / `yes_ask_dollars` | string | Bid/ask |
| `volume_24h_fp` | string | 24h volume in contracts (multiply × `notional_value_dollars` for $) |
| `volume_fp` | string | Lifetime volume in contracts |
| `open_interest_fp` | string | OI in contracts — at **market** level (unlike Polymarket's event-level) |
| `notional_value_dollars` | string | Always `"1.0000"` for binary markets |
| `close_time` | string | ISO datetime |
| `status` | string | `active`, `closed`, `settled` |

**Event object fields (relevant):**
| Field | Notes |
|---|---|
| `event_ticker` | Primary event identifier |
| `series_ticker` | Series group, e.g. `KXINFL` |
| `title` | Human-readable event name |
| `category` | e.g. `Economy`, `Elections`, `World` |
| `mutually_exclusive` | `true` for multi-outcome markets (Pope, election winner) |

**Authentication:** Public market data endpoints appear to work without auth. An API key is available via the developer dashboard. Rate limits are documented as token-budget tiers but not publicly enumerated. Recommend using without auth initially and adding key if throttled.

**Key difference from Polymarket:** 24h price change must be computed as `last_price_dollars - previous_price_dollars`. Polymarket returns `oneDayPriceChange` directly; Kalshi does not — but `previous_price_dollars` is always present, so no extra API call.

---

## Gaps vs Polymarket Parity

### 1. Whitelist identifier format
Polymarket uses a URL slug (`how-many-fed-rate-cuts-in-2026`) that maps cleanly to human-readable Polymarket URLs. Kalshi uses tickers (`KXINFL-26-B3PT5`).

**Problem:** Users add markets via `/add [url]`. A Kalshi URL like `kalshi.com/markets/KXINFL/KXINFL-26-B3PT5` contains the ticker in the path. The slug-extraction pattern we wrote for Polymarket needs a Kalshi variant.

**Decision needed:** Do we parse `kalshi.com/markets/SERIES/TICKER` from the URL, or require users to input the ticker directly?

**Suggestion:** Parse from URL. Pattern: `kalshi.com/markets/[series]/[ticker]` → extract the last path segment as `ticker`.

### 2. Multi-outcome events
Kalshi has `mutually_exclusive: true` events with many legs (e.g., "Who will be the next Pope?" with 7+ candidates, each a separate market). Polymarket has the same structure.

**Problem:** `/add [kalshi_url]` on a Pope market adds one candidate. That may be fine — but the digest shows "Who will the next Pope be? Yes 4.7%" which is confusing without context of what "Yes" means.

**Decision needed:** For mutually_exclusive events, do we track individual legs or the whole event?

**Suggestion:** Track individual legs only (consistent with Polymarket behavior). Use `yes_sub_title` / `title` to surface the specific outcome. Flag this for future enhancement if needed.

### 3. Volume in dollar terms
Kalshi `volume_24h_fp` is in contracts, not dollars. `notional_value_dollars` is always `"1.0000"` for binary markets, so `volume_24h_fp` equals dollar volume 1:1. This should be validated but is likely safe to treat as equivalent.

### 4. OI data location
Polymarket OI is at the **event** level. Kalshi OI (`open_interest_fp`) is at the **market** level. This is actually better — no extra lookup needed.

### 5. Digest formatting
Current digest header says "Polymarket". With Kalshi added, need to either:
- Add a source label per market line (`• Kalshi` / `• Polymarket`)
- Split the digest into sections by source

**Decision needed:** Unified digest with per-market source label vs separate sections?

**Suggestion:** Single section, sorted by expiry, with a source tag after each link line. Keeps the digest compact.

### 6. Price alert source routing
Pings Lambda currently fires for all whitelist entries and formats links as `polymarket.com/event/[slug]`. With Kalshi entries in the whitelist, pings need to detect source and route correctly.

**Decision needed:** Add a `source` field to whitelist entries (`polymarket` / `kalshi`) and branch on it in both digest and pings.

**Suggestion:** Yes — `source` field on every whitelist entry. `/add polymarket.com/...` → source=polymarket, `/add kalshi.com/...` → source=kalshi. No user-facing change needed.

### 7. Authentication
Kalshi has an API key system but public data endpoints appear unauthenticated. 

**Decision needed:** Get an API key now or wait until throttled?

**Suggestion:** Start unauthenticated. If we hit rate limits, add a key stored in S3 config (same pattern as whitelist). No code change needed beyond adding an `Authorization` header.

---

## Implementation Plan

**Step 1 — Whitelist schema extension**
- Add `source` field to `whitelist.json` entries: `"source": "polymarket"` or `"source": "kalshi"`
- Update webhook `/add` handler to detect Kalshi URLs by checking for `kalshi.com` in the URL
- Add `extract_kalshi_ticker(url)` alongside existing `extract_slug(url)`
- For Kalshi `/add`: call `GET /events/{event_ticker}` derived from URL to resolve title and validate ticker exists
- Existing Polymarket entries remain unchanged (backward compatible)

**Step 2 — Digest extension**
- In `fetch_contracts()`, branch on `source` per whitelist entry
- Add `fetch_kalshi_market(ticker)` function: `GET /markets/{ticker}` or derive from events endpoint
- Compute `price_change_24h = float(last_price_dollars) - float(previous_price_dollars)`
- Volume: `float(volume_24h_fp) * float(notional_value_dollars)` (effectively 1:1 for binary)
- OI: `float(open_interest_fp)` (market-level, already where we need it)
- Add `source` field to `Contract` dataclass
- Digest format: Polymarket and Kalshi markets shown together, sorted by expiry, with source shown inline per market — not split into separate sections. This mirrors the inspiration format (see `pmtgbot_prd.docx`) where both venues appear on the same event line so the desk can see pricing from each source at a glance. Example:

```
── Dec 31 ──
Will no Fed rate cuts happen in 2026?
  Polymarket   Yes 79.9% (+0.4% 24h)  |  $61k 24h vol  |  $1.4M OI
  Kalshi       Yes 77.0% (+0.2% 24h)  |  $43k 24h vol  |  $980k OI
```

- For events tracked on both venues independently (different whitelist entries), they appear as separate lines since they have different expiry dates. True side-by-side cross-venue display (same event, two rows) is a P3 enhancement.

**Step 3 — Pings extension**
- Same branching in `fetch_markets()`: Kalshi entries use new fetch function
- Alert link format: `kalshi.com/markets/[series]/[ticker]` derived from ticker
- No threshold logic change needed

**Step 4 — Deploy and test**
- Extend Lambda deployment zips (no new dependencies — `requests` and `boto3` already present)
- Test: `/add` a live Kalshi market → verify whitelist entry → invoke digest Lambda → confirm Kalshi market appears
- Test: seed stale price for Kalshi entry in prices.json → invoke pings → confirm alert fires with correct Kalshi link

---

## Scope

**P2 (this PRD) — Kalshi parity**
- `/add kalshi.com/...` whitelist support
- Kalshi markets in digest (price, 24h change, vol, OI, link)
- Kalshi markets in price pings

**Out of scope / future**
- Kalshi API key / authentication
- Multi-leg event tracking
- Cross-platform arbitrage display (Polymarket vs Kalshi same event)
- Kalshi Perps / perpetual futures API

---

## Key Risks

1. **Ticker stability** — Kalshi tickers appear stable (`KXINFL-26-B3PT5` is the permanent ID for a market). Less ambiguous than Polymarket slugs which can change. Low risk.
2. **`previous_price_dollars` semantics** — Not fully documented. Likely prior day's close but could be prior settlement. Worth validating against a known market before relying on it for 24h change.
3. **Unauthenticated rate limits** — Unknown. If we hit them, adding an API key is a one-line fix (header injection). Low operational risk.
4. **`volume_24h_fp` = dollars assumption** — Holds if `notional_value_dollars` is always 1.0 for binary markets. Seen in all sampled data. Should add a runtime assert or log if it deviates.

---

## Open Questions for Discussion

1. **Unified vs split digest sections** — one section sorted by expiry (with source tags) or separate "Polymarket" / "Kalshi" blocks?
2. **`previous_price_dollars` validation** — do we want to run a sanity check before shipping, or trust the field?
3. **Multi-leg events** — the Pope market is a clear case where the current approach ("Yes 4.7%" for one candidate) may confuse. Flag for P3 or address now?
4. **Is it worth it?** — Kalshi's API is clean and the data aligns well. The main cost is the `source` branching logic and URL parsing. Implementation is roughly 2–3 hours of code changes, no new infra, no new dependencies. The payoff is coverage of a major complementary prediction market venue. Recommend proceeding.
