
# IN LAMBDA: Add wrapper Function for Lambda Execution

import requests
import datetime
from datetime import datetime, timedelta, timezone
import pandas as pd
import numpy as np
import json
import ast

# ------------ Create Dataclass for each contract fetched ------------ #
# This will make it easier to fetch and organize information about each contract
# This is the information that we fetch from the API to display on the bot
from dataclasses import dataclass

@dataclass
class Contract:
    name_slug : str # Contract name
    curr_price : float # YES price
    vol_24h : float # 24h volume, volume traded over past 24h
    vol_1w : float # 1 week volume, volume traded over past week
    open_interest : float # open interest
    mvmt_level : float # defined_zscore_metric
    expiry_date : datetime # Expiry date
    title : str
    
    # Other useful stuff to keep track of, that we won't be displaying
    cond_id : str

# ------------ API Calls : Define which markets to pull ---------------- #
# Here we define what markets we want to look at. Currently pulling:
# 1. Everything that expires in the next 30 days
# 2. Relevant to tags: Fed Rates, Fed, Economy, Jobs Report < Can easily be changed if we want different kinds of news >
# It takes a little bit of work/trial and error to find the relevant tags re poor tagging on Polymarket server side

# Gamma API endpoint
BASE_URL = "https://gamma-api.polymarket.com/events"

# Tags for fetching relevant events
MACRO_TAGS = [
    "100196",  # Fed Rates
    "100328",  # Economy
    "159",     # Fed
    "102548",  # Jobs Report
]

# Organization: Dictionary with Contract Name : Condition ID
digest_markets = dict() # Returns dictionary with contract name : condition id for desired contracts

def fetch_macro_titles_next_30d(limit=200):
    now = datetime.now(timezone.utc)
    first = now + timedelta(days=0)
    cutoff = now + timedelta(days=30)

    seen_ids = set()
    events = []

    # Fetch all markets that match relevant tags
    for tag in MACRO_TAGS:
        res = requests.get(
            BASE_URL,
            params={
                "closed": "false",
                "tag_id": tag,
                "limit": 100,
                "end_date_min": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "end_date_max": cutoff.strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
        )
        res.raise_for_status()
        
        for event in res.json():
            event_volume = float(event.get("volume", 0))
            if (event["id"] not in seen_ids) and (event_volume >= 75000):
                seen_ids.add(event["id"])
                events.append(event)


    # Filter down to those that expire in next 30 days
    for event in events:
        # First decide which market in the event we want to focus on. We choose to display
        # the market with the highest YES odds
        markets = event.get("markets", [])
        best_market = None
        best_yes_prob = -1

        for market in markets:
            try:
                raw = market.get("outcomePrices")
                if not raw: 
                    continue
                outcome_prices = json.loads(market.get("outcomePrices"))
    
                if not outcome_prices:
                    continue

                # YES is usually index 0
                yes_prob = float(outcome_prices[0])
                if yes_prob > best_yes_prob:
                    best_yes_prob = yes_prob
                    best_market = market
            
            except Exception as e:
                print("Error parsing market:", e)
                continue

        # Now that we have the desired market within our contract, use this to filter
        # Parse expiry
            end_date_str = market.get("endDate")
            if not end_date_str:
                continue

            try:
                end_date = datetime.fromisoformat(
                end_date_str.replace("Z", "+00:00")
                )
            except ValueError:
                continue

        # Only keep markets expiring in the next 30 days
        if not (now <= end_date <= cutoff):
            continue

        # Add markets in expiry date window to dictionary
        try:
            slug = event.get("slug") or event.get("eventSlug") # Note: a slug is specific to an EVENT
            condition_id = best_market.get("conditionId") # A conditionId is specific to a MARKET

            if not slug or not condition_id:
                continue

            digest_markets[slug] = condition_id
                
        except Exception as e:
            print("Error parsing market:", e)

    # returned: dictionary of event slug : condition ID of desired market within this event
    return digest_markets

# Run the function we just wrote
next30d_events = fetch_macro_titles_next_30d()

# ----------- Local Storage -------------- #
# We now want to store all the contracts we are tracking in our dictionary as 'Contract' objects locally
# This avoids making an API call every single time we need to interface with Contract information, essentially filling out the
# Contract object container (defined in the first section) for each contract
contracts = dict()
for key, value in next30d_events.items():
    # First, make API call to fetch desired properties for desired market
    condition_id = str(value)

    resp = requests.get(
    "https://gamma-api.polymarket.com/markets",
    params={"condition_ids": condition_id}
)
    data = resp.json()

    if not data:
        continue

    market = data[0]

    outcomes = market["outcomes"]
    token_ids = market["clobTokenIds"]
    
    yes_token_id = token_ids[outcomes.index("Yes")]  
    arr = ast.literal_eval(token_ids)
    yes_token_id = arr[0]  

    # Expiry date
    expiry = market["endDate"]

    # 24h Volume
    vol_24h = market.get("volume24hr")

    # 7d Volume
    vol_7d = market.get("volume1wk")

    # Title
    title = market.get("question")
    
    # Open Interest -- NEED TO FIX
    oi = float(market.get("liquidity"))

    # Price of YES
    resp = requests.get(
    "https://clob.polymarket.com/price",
    params={
        "token_id": yes_token_id,
        "side": "BUY"
    }
)

    data = resp.json()
    price = data.get("price")


    # Z Score Defined Mvmt Level Metric -- NEED FIX
    mvmt_level = ...
    
    # populate Contract dataclass with API information
    temp = str(key)
    contracts[temp] = Contract(
        name_slug=key,
        curr_price=price,
        vol_24h=vol_24h,
        vol_1w=vol_7d,
        open_interest=oi,
        mvmt_level=1,
        expiry_date=expiry,
        cond_id=condition_id,
        title = title)
    

# # --------- Sorting + Formatting ---------- #
# # In this section we render the text that will be outputting in daily digest messages
text = "== CALENDAR • Next 30 days ===" +'\n\n'
def format_contract(contract):
    # Parse expiry date
    expiry = datetime.fromisoformat(contract.expiry_date.replace("Z", ""))
    expiry_str = expiry.strftime("%A, %B %d")

    # price formatting
    yes_price = float(contract.curr_price) * 100
    yes_str = f"Yes {yes_price:.1f}%"

    # volume formatting
    vol_24h = (
        f"${contract.vol_24h:,.0f} 24h Volume"
        if contract.vol_24h is not None
        else "<FETCH> 24h Volume"
    )

    oi = (
        f"${contract.open_interest:,.0f} OI"
        if contract.open_interest is not None
        else "None OI"
    )

    return (
    f"{expiry_str}\n"
    f"'{contract.title}'\n"
    f"{yes_str}, {vol_24h}, {oi}\n"
    f"https://polymarket.com/event/{contract.name_slug}"
)

# Sort by date
items = contracts.items()

sorted_contracts = sorted(
    items,
    key=lambda item: item[1].expiry_date
)

for key, contract in sorted_contracts:
    text += format_contract(contract) + "\n\n"


# ----------- Sending to Telegram: Daily Digest --------------- #
BOT_TOKEN = "8819186886:AAHQnJWYoU98thFHXXgn407rAJZUbuB6xaY"
CHAT_ID = "-1004368186213"

def send_telegram_message(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    text = text

    payload = {
        "chat_id": CHAT_ID,
        "text": text,
    }
    
    response = requests.post(url, json=payload)

    print(response.status_code)
    print(response.text)

send_telegram_message(text)

text_depricated = """ — Confirmed movers —
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
