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


# fetch prices over last 31 days (of YES)
def get_history(condition_id : str):
    token_id = get_token_ids(condition_id)
    url = "https://clob.polymarket.com/prices-history"

    end = int(datetime.now(timezone.utc).timestamp())
    start = int((datetime.now(timezone.utc) - timedelta(days=31)).timestamp())

    params = {
        "market": token_id,
        "startTs": start,
        "endTs": end,
        "interval": "1d", 
        "fidelity": 60
    }

    res = requests.get(url, params=params)
    history = res.json()["history"]
    return history

# calculate differences between prices
def get_differences(condition_id : str):
    history = get_history(condition_id)
    prices = [point["p"] for point in history]
    price_changes = np.diff(prices)
    std_dev = np.std(price_changes)

    return std_dev # desired metric


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

def event_driven_pings():
    # get the volume of chosen market
    vol = ...
    if vol >= 1000000 and vol < 10000000:
        ...
    elif vol >= 10000000 and vol < 100000000:
        ...
    elif vol >= 100000000:
        ...

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
