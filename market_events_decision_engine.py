import requests
import datetime
from datetime import datetime, timedelta, timezone
import pandas as pd
import numpy as np


# ------------ API Calls : Define Markets To Pull ---------------- #
# Gamma API endpoint
url = "https://gamma-api.polymarket.com/events"
digest_markets = dict() # Returns dictionary with contract name : condition id for desired contracts
queries = [
    "Fed interest rates",
    "inflation CPI",
    "US recession GDP",
    "unemployment jobs report",
    "oil prices macro",
]

markets = []
for q in queries:
    res = requests.get(
        "https://gamma-api.polymarket.com/markets",
        params={"search": q, "limit": 50}
    )
    markets.extend(res.json())


# 
#params = {
#    "tag_slug": "politics",
#    "liquidity_min": 10000,
#    "closed": "false",  # Only active events
#    "limit": 100
#}

#response = requests.get(url, params=params)
#response.raise_for_status()

#events = response.json()

#print(f"Found {len(events)} events")

#for event in events:
#    print(event["title"])


# ----------- Sorting & Formatting -------------- #
# Define 'movement level' for a contract (own function)

def get_token_ids(condition_id: str):
    url = "https://gamma-api.polymarket.com/markets"

    params = {
        "condition_ids": condition_id
    }

    res = requests.get(url, params=params)
    data = res.json()

    if not data:
        raise ValueError("No market found for condition_id")

    market = data[0]
    # clobTokenIds is usually ["YES_TOKEN", "NO_TOKEN"]
    token_ids = market.get("clobTokenIds")

    if isinstance(token_ids, str):
        token_ids = eval(token_ids)  # sometimes returned as stringified list

    yes_token = token_ids[0]
    return yes_token


# ------------ Sorting Output (Formatting for Telegram Bot) ---------------

# Sort contracts by expiry date (list nearest ones first, include contracts expiring now - 72H in future)

# Formatting: Title
# Movement Level
# X% now, from y% 24h ago
# Vol traded over past 24H
# Expiry date
# url to contract

# ------------ Event Driven Pings --------------- #
# Send pings if: volume or price spikes meaningfully

# fetches 31-day daily price history from CLOB for a given YES token — used by event_driven_pings for z-score baseline
def get_history(token_id: str):
    end = int(datetime.now(timezone.utc).timestamp())
    start = int((datetime.now(timezone.utc) - timedelta(days=31)).timestamp())

    res = requests.get(
        "https://clob.polymarket.com/prices-history",
        params={"market": token_id, "startTs": start, "endTs": end, "interval": "1d", "fidelity": 60}
    )
    return res.json().get("history", [])

# returns std dev of daily price changes for a market — used by event_driven_pings to compute z-score
def get_differences(token_id: str):
    history = get_history(token_id)
    if not history:
        return 0.01
    prices = [point["p"] for point in history]
    price_changes = np.diff(prices)
    return np.std(price_changes)

def event_driven_pings():
    for market in markets:
        # Filter: skip markets below $1M all-time volume
        vol = float(market.get("volume") or 0)
        if vol < 1_000_000:
            continue

        if vol >= 100_000_000:
            threshold = 0.0025
        elif vol >= 10_000_000:
            threshold = 0.025
        else:
            threshold = 0.05

        # Parse YES token ID from clobTokenIds
        token_ids = market.get("clobTokenIds")
        if isinstance(token_ids, str):
            token_ids = eval(token_ids)
        if not token_ids:
            continue
        token_id = token_ids[0]

        # Fetch 2h price history from CLOB
        end = datetime.now(timezone.utc)
        start = end - timedelta(hours=2)
        res = requests.get(
            "https://clob.polymarket.com/prices-history",
            params={
                "market": token_id,
                "startTs": int(start.timestamp()),
                "endTs": int(end.timestamp()),
                "fidelity": 1,
            }
        )
        history = res.json().get("history", [])
        if len(history) < 2:
            continue

        # Calculate price delta over 2h window
        price_start = history[0]["p"]
        price_end   = history[-1]["p"]
        delta = abs(price_end - price_start)

        if delta < threshold:
            continue

        # Z-score label
        std_dev = get_differences(token_id)
        today_move = price_end - price_start
        z = abs(today_move) / max(std_dev, 0.01)
        if z >= 2:
            z_label = "Major movement (z>2)"
        elif z >= 1:
            z_label = "Notable movement (1<z<2)"
        else:
            z_label = "Normal movement (z<1)"

        # Format and send alert
        direction = "up" if price_end > price_start else "down"
        timestamp = datetime.now(timezone.utc).strftime("%-d %b, %H:%M ET")
        question  = market.get("question", "")
        curr_pct  = round(price_end * 100)
        prev_pct  = round(price_start * 100)
        vol_24h   = market.get("volume24hr", "N/A")
        oi        = market.get("openInterest", "N/A")
        end_date  = market.get("endDate", "")[:10]
        slug      = market.get("slug", "")

        text = (
            f"*PREDICTION MARKET ALERT*\n"
            f"{timestamp} — Polymarket\n"
            f"{question}\n"
            f"Yes {curr_pct}% now, from {prev_pct}% 2h ago ({direction})\n"
            f"${vol_24h} 24h vol\n"
            f"${oi} OI · {z_label}\n"
            f"resolves {end_date}\n"
            f"polymarket.com/event/{slug}"
        )
        send_telegram_message(text)

# ----------- Daily Digest ---------------- #
# Selected markets, give contract name, price / price 24h ago, vol / vol 24h ago, resolution date, link -- SUBJECT TO CHANGE
# markets is dictionary with contract name : condition_id
def daily_digest(digest_markets : str):
    out_str = ""
    for market_name, condition_id in digest_markets.items():
        url = f"https://gamma-api.polymarket.com/markets?condition_ids={condition_id}"

        res = requests.get(url)
        res.raise_for_status()

        market = res.json()[0]

        name = market["question"]      # Contract name
        end_date = market["endDate"]       # Resolution date
        curr_volume = market["volume"]      # Current cumulative volume 
        token_ids = market["clobTokenIds"]  # Token IDs for price history
        curr_yes_price = float(market["outcomePrices"][0]) # current price, flag possibly wrong key
    
        url = "https://clob.polymarket.com/prices-history"

        end = datetime.now(timezone.utc)
        start = end - timedelta(days=1)

        params = {
        "market": token_id,
        "startTs": int(start.timestamp()),
        "endTs": int(end.timestamp()),
        "interval": "max",
        "fidelity": 60,
        }

        history = requests.get(url, params=params).json()["history"]

        price_24h_ago = history[0]["p"]
        current_price = history[-1]["p"]



# ----------- Sending to Telegram --------------- #
BOT_TOKEN = "8819186886:AAHQnJWYoU98thFHXXgn407rAJZUbuB6xaY"
CHAT_ID = "-1004368186213"

def send_telegram_message(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    text = text

    payload = {
        "chat_id": CHAT_ID,
        "text": text,
    }
    
    requests.post(url, json=payload)
    response = requests.post(url, json=payload)

    print(response.status_code)
    print(response.text)

text = """ — Confirmed movers —
Govt shutdown before Oct 1? Major movement (z>2)
– 44% now, from 31% 24h ago
– vol $1.8M 24h, vs $0.7M prior
– resolves Oct 1
– polymarket.com/event/govt-shutdown-before-oct-1

Fed cuts at July FOMC? Normal movement (z<1)
– 71% now, from 59% 24h ago
– vol $620k 24h, vs $310k prior
– resolves Jul 30
– polymarket.com/event/fed-cuts-july-fomc

ECB cuts in July? Notable movement (1<z<2)
– 15% now, from 22% 24h ago
– vol $410k 24h, vs $560k prior
– resolves Jul 24
– polymarket.com/event/ecb-cuts-in-july

— Resolving in 72h —
SCOTUS ruling by Fri? Normal movement (z<1)
– 63% — vol $220k 24h, vs $140k prior
– resolves Jun 17
– polymarket.com/event/scotus-ruling-case

Jobless claims above 250k? Normal movement (z<1)
– 40% — vol $180k 24h, vs $190k prior
– resolves Jun 18
– polymarket.com/event/jobless-claims-250k
"""
send_telegram_message(text)

# ---------- Scheduling with AWS Lambda ------------- #

event_driven_pings()  # uncomment to test locally; remove before Lambda deployment
