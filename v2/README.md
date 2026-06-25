# Galaxy Terminal — Prediction Market TG Bot (v2)

This is the v2 rebuild of the Galaxy S&T prediction market Telegram bot. The original bot (`galaxy_terminal`) had working infrastructure but poor signal quality — too many low-relevance markets, broken event-driven alerts, and no way to curate what the desk actually tracked. V2 addresses all of that without changing the underlying stack.

---

## What It Does

Two outputs, push-based:

1. **Daily digest** — sent at 8:15am and 4:00pm ET. Shows all whitelisted markets grouped by expiry date, with current price, 24h price change, 24h volume, and open interest.
2. **Price movement alerts** — fires within ~1 minute of a significant move on any whitelisted market. Uses volume-tiered thresholds so large markets aren't constantly alerting on noise.

---

## Stack

No new infrastructure was introduced in v2. Everything runs on the existing setup:

| Component | What it does |
|---|---|
| **AWS Lambda** — `galaxy-terminal-digest` | Runs the daily digest on schedule |
| **AWS Lambda** — `galaxy-terminal-pings` | Runs every 1 minute, checks for price moves |
| **AWS Lambda** — `galaxy-terminal-webhook` | Handles Telegram slash commands |
| **AWS EventBridge** | Schedules digest (2×/day) and pings (every 1 min) |
| **AWS S3** — `galaxy-terminal-config` | Stores `whitelist.json` and `prices.json` |
| **API Gateway** | Routes Telegram webhook POST → `galaxy-terminal-webhook` Lambda |
| **Telegram Bot API** | Sends messages; bot is `@predmarket_update_bot` |
| **Polymarket Gamma API** | Market data source (`gamma-api.polymarket.com`) |

---

## Key Decisions

### 1. Whitelist over tag-based filtering
The original bot fetched markets by tag, returning a large unfiltered corpus. V2 replaced this with a curated whitelist stored in S3. Only markets explicitly added to the whitelist appear in the digest or trigger alerts. This was the primary lever for improving signal-to-noise.

The whitelist lives at `s3://galaxy-terminal-config/whitelist.json` and is read by every Lambda on each invocation.

### 2. Whitelist managed via Telegram slash commands
The whitelist is managed in-channel using three commands:
- `/add [polymarket url]` — adds a market to the whitelist
- `/remove [polymarket url]` — removes a market
- `/list` — shows all currently tracked markets as clickable links

This avoids any need to touch AWS directly to update what's tracked. The webhook Lambda resolves the market slug to a `condition_id` via the Gamma API on `/add`, so the stored entry always has both.

S3 was chosen as the config store over alternatives (hardcoded list, DynamoDB, SSM) because it requires no new infrastructure and the whitelist is a simple JSON array that doesn't need query capability.

### 3. Polymarket data source: Gamma API only
The original implementation used the Polymarket CLOB API for price data (`/price` endpoint), which was returning 404s. V2 uses only the Gamma API (`gamma-api.polymarket.com/events`), which returns `lastTradePrice`, `volume24hr`, `oneDayPriceChange`, and event-level `openInterest` in a single call — no secondary lookups needed.

Key field locations (non-obvious):
- **Open interest** lives at the **event** level in Gamma, not the market level. The market-level `liquidity` field is different and was incorrectly used in v1.
- **24h price change** (`oneDayPriceChange`) is returned directly — no price history calls needed.

### 4. Event-driven pings via S3 price history
The original pings implementation had multiple crash bugs and relied on the CLOB `/prices-history` endpoint, which returns empty for most markets. V2 rewrites pings entirely:

- After each run, the pings Lambda writes current prices to `s3://galaxy-terminal-config/prices.json` (keyed by `condition_id`)
- On the next run (1 minute later), it reads that file and computes the delta
- If the move exceeds the threshold for that market's volume tier, it fires an alert

This means the first run after a cold start produces no alerts (no baseline yet), which is the correct behavior.

**Volume-tiered alert thresholds:**
| Lifetime volume | Min move to alert |
|---|---|
| $10M+ | 1.25% |
| $1M–$10M | 2.5% |
| $100k–$1M | 3.0% |
| Under $100k | No alerts |

### 5. IAM role
Lambda execution role is `glxy-pmtgbot-lambda-role`. Requires `AmazonS3FullAccess` (not ReadOnly) because the pings Lambda writes `prices.json` on every run. The webhook Lambda also writes `whitelist.json` on `/add` and `/remove`.

---

## File Structure

```
galaxy_terminal/
├── calendar_updates/
│   ├── market_events_decision_engine.py   # Digest logic
│   └── lambda_function.py                 # Lambda entrypoint (calls run_all())
├── event_pings/
│   └── event_driven_pings.py              # Price movement alert logic
├── webhook/
│   └── lambda_function.py                 # Slash command handler
├── prd_v2.md                              # Full product PRD (P0–P3 scope)
├── kalshi_prd.md                          # Kalshi integration PRD (P2)
├── pmtgbot_prd.docx                       # Original brief and inspiration
└── output_v0.png                          # v0 bot output (reference)
```

---

## Digest Format

```
PREDICTION MARKET DIGEST
Jun 25, 2026 — Polymarket

── Jun 30 ──
Strait of Hormuz traffic returns to normal by end of June?
Yes 4.2% (-0.2% 24h)  |  $1.8M 24h vol  |  $7.0M OI
polymarket.com/event/strait-of-hormuz-traffic-returns-to-normal-by-end-of-june

── Dec 31 ──
Will no Fed rate cuts happen in 2026?
Yes 79.9% (+0.4% 24h)  |  $61k 24h vol  |  $1.4M OI
polymarket.com/event/how-many-fed-rate-cuts-in-2026
```

---

## Alert Format

```
MARKET ALERT
Jun 25, 12:43 UTC — Polymarket

Will no Fed rate cuts happen in 2026?
▲ Yes 79.1% (+9.1%)  |  $61k 24h vol
polymarket.com/event/how-many-fed-rate-cuts-in-2026
```

---

## Roadmap

See `prd_v2.md` for full scope. Summary:

- **P0 ✅** — Whitelist, digest formatting, slash commands, EventBridge schedules
- **P1 ✅** — Event-driven pings, 24h price change in digest
- **P2** — Kalshi integration (see `kalshi_prd.md`)
- **P3** — Auto-expiry, activity score, Z-score, tiered whitelist
