import json
import boto3
import requests
from datetime import datetime, timezone

S3_BUCKET = "galaxy-terminal-config"
WHITELIST_KEY = "whitelist.json"
PRICES_KEY = "prices.json"

BOT_TOKEN = "8819186886:AAHQnJWYoU98thFHXXgn407rAJZUbuB6xaY"
CHAT_ID = "-1004368186213"

GAMMA_BASE = "https://gamma-api.polymarket.com"

# Volume-tiered movement thresholds
THRESHOLDS = [
    (10_000_000, 0.025),
    (1_000_000,  0.035),
    (100_000,    0.04),
]

def get_threshold(lifetime_vol):
    for min_vol, threshold in THRESHOLDS:
        if lifetime_vol >= min_vol:
            return threshold
    return None  # below $100k — skip

# ------------ S3 Helpers ------------ #
def s3_read(key):
    s3 = boto3.client("s3")
    try:
        obj = s3.get_object(Bucket=S3_BUCKET, Key=key)
        return json.loads(obj["Body"].read().decode("utf-8"))
    except s3.exceptions.NoSuchKey:
        return {}

def s3_write(key, data):
    s3 = boto3.client("s3")
    s3.put_object(
        Bucket=S3_BUCKET,
        Key=key,
        Body=json.dumps(data, indent=2).encode("utf-8"),
        ContentType="application/json",
    )

# ------------ Fetch Markets ------------ #
def fetch_markets(whitelist):
    markets = []
    for entry in whitelist:
        slug = entry["slug"]
        condition_id = entry["condition_id"]

        resp = requests.get(f"{GAMMA_BASE}/events", params={"slug": slug})
        resp.raise_for_status()
        data = resp.json()
        if not data:
            continue

        event = data[0]
        lifetime_vol = float(event.get("volume") or 0)
        oi = float(event.get("openInterest") or 0)

        market = next(
            (m for m in event.get("markets", []) if m.get("conditionId") == condition_id),
            None
        )
        if not market:
            continue

        price = float(market.get("lastTradePrice") or 0)
        vol_24h = float(market.get("volume24hr") or 0)
        title = market.get("question", slug)

        markets.append({
            "slug": slug,
            "condition_id": condition_id,
            "title": title,
            "price": price,
            "vol_24h": vol_24h,
            "lifetime_vol": lifetime_vol,
            "oi": oi,
        })

    return markets

# ------------ Formatting ------------ #
def md_escape(text):
    for ch in r"\_*[]()~`>#+-=|{}.!":
        text = str(text).replace(ch, f"\\{ch}")
    return text

def format_alert(market, prev_price, move):
    direction = "▲" if move > 0 else "▼"
    move_pct = abs(move) * 100
    yes_pct = market["price"] * 100
    slug = market["slug"]

    vol_str = md_escape("$" + f"{market['vol_24h']/1000:.0f}k")
    yes_str = md_escape(f"{yes_pct:.1f}%")
    sign = "+" if move > 0 else "-"
    move_str = md_escape(f"{sign}{move_pct:.1f}%")
    date_str = md_escape(datetime.now(timezone.utc).strftime("%b %d, %H:%M UTC"))

    return "\n".join([
        "*MARKET ALERT*",
        f"_{date_str} — Polymarket_",
        "",
        f"[{md_escape(market['title'])}](https://polymarket.com/event/{slug})",
        f"{direction} Yes {yes_str} \\({move_str}\\)  _\\|  {vol_str} 24h vol_",
    ])

# ------------ Send to Telegram ------------ #
def send_telegram_message(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    resp = requests.post(url, json={
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "MarkdownV2",
        "disable_web_page_preview": True,
    }, timeout=10)
    print(f"Telegram response: {resp.status_code} {resp.text}")

# ------------ Entry Point ------------ #
def run_all():
    whitelist = s3_read(WHITELIST_KEY)
    if not whitelist:
        print("Whitelist empty — nothing to check.")
        return

    prev_prices = s3_read(PRICES_KEY)
    markets = fetch_markets(whitelist)

    new_prices = {}
    for market in markets:
        cid = market["condition_id"]
        current_price = market["price"]
        new_prices[cid] = current_price

        prev_price = prev_prices.get(cid)
        if prev_price is None:
            continue  # first run, no baseline yet

        threshold = get_threshold(market["lifetime_vol"])
        if threshold is None:
            continue  # below minimum volume, skip

        move = current_price - prev_price
        if abs(move) >= threshold:
            alert = format_alert(market, prev_price, move)
            send_telegram_message(alert)
            print(f"Alert sent for {market['slug']}: {move:+.4f}")
        else:
            print(f"No move: {market['slug']} ({abs(move):.4f} < {threshold})")

    s3_write(PRICES_KEY, new_prices)

if __name__ == "__main__":
    run_all()
