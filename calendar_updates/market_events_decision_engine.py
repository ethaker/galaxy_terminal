import requests
import json
import boto3
from datetime import datetime, timezone
from dataclasses import dataclass

# ------------ Contract Dataclass ------------ #
@dataclass
class Contract:
    name_slug: str
    curr_price: float
    vol_24h: float
    open_interest: float
    expiry_date: str
    title: str
    cond_id: str
    price_change_24h: float = 0.0

# ------------ S3 Config ------------ #
S3_BUCKET = "galaxy-terminal-config"
S3_KEY = "whitelist.json"

def load_whitelist():
    try:
        s3 = boto3.client("s3")
        obj = s3.get_object(Bucket=S3_BUCKET, Key=S3_KEY)
        entries = json.loads(obj["Body"].read().decode("utf-8"))
        return {e["slug"]: e["condition_id"] for e in entries}
    except Exception as e:
        print(f"Failed to load whitelist from S3: {e}")
        return {}

# ------------ Telegram Config ------------ #
BOT_TOKEN = "8819186886:AAHQnJWYoU98thFHXXgn407rAJZUbuB6xaY"
CHAT_ID = "-1004368186213"

# ------------ Fetch Markets ------------ #
def fetch_contracts(whitelist):
    contracts = []
    for slug, condition_id in whitelist.items():
        resp = requests.get(
            "https://gamma-api.polymarket.com/events",
            params={"slug": slug}
        )
        resp.raise_for_status()
        data = resp.json()

        if not data:
            print(f"No data returned for {slug}")
            continue

        event = data[0]

        # OI lives at event level
        oi = float(event.get("openInterest") or 0)

        # Match the specific market by condition ID for price and volume
        market = next(
            (m for m in event.get("markets", []) if m.get("conditionId") == condition_id),
            None
        )
        if not market:
            print(f"Condition ID {condition_id} not found in event {slug}")
            continue

        try:
            price = float(market.get("lastTradePrice") or 0)
            vol_24h = float(market.get("volume24hr") or 0)
            price_change_24h = float(market.get("oneDayPriceChange") or 0)
            expiry = event.get("endDate") or market.get("endDate", "")
            title = market.get("question", slug)

            contracts.append(Contract(
                name_slug=slug,
                curr_price=price,
                vol_24h=vol_24h,
                open_interest=oi,
                expiry_date=expiry,
                title=title,
                cond_id=condition_id,
                price_change_24h=price_change_24h,
            ))
        except Exception as e:
            print(f"Error parsing market {slug}: {e}")

    return contracts

# ------------ Formatting ------------ #
def format_volume(val):
    if val >= 1_000_000:
        return f"${val / 1_000_000:.1f}M"
    if val >= 1_000:
        return f"${val / 1_000:.0f}k"
    return f"${val:.0f}"

def md_escape(text):
    """Escape special characters for MarkdownV2."""
    for ch in r"\_*[]()~`>#+-=|{}.!":
        text = text.replace(ch, f"\\{ch}")
    return text

def format_digest(contracts):
    now = datetime.now(timezone.utc)
    date_str = now.strftime("%b %d, %Y")

    lines = [
        f"*PREDICTION MARKET DIGEST*",
        f"_{md_escape(date_str)} — Polymarket_",
        "",
    ]

    sorted_contracts = sorted(contracts, key=lambda c: c.expiry_date)

    current_date_header = None
    for c in sorted_contracts:
        try:
            expiry_dt = datetime.fromisoformat(c.expiry_date.replace("Z", "+00:00"))
            date_header = expiry_dt.strftime("%b %d")
        except Exception:
            date_header = "Unknown date"

        if date_header != current_date_header:
            current_date_header = date_header
            lines.append(f"*── {md_escape(date_header)} ──*")

        yes_pct = md_escape(f"{c.curr_price * 100:.1f}%")
        vol = md_escape(format_volume(c.vol_24h))
        oi = md_escape(format_volume(c.open_interest))
        change = c.price_change_24h * 100
        sign = "+" if change >= 0 else ""
        change_str = md_escape(f"{sign}{change:.1f}%")

        lines.append(f"[{md_escape(c.title)}](https://polymarket.com/event/{c.name_slug})")
        lines.append(f"Yes {yes_pct} \\({change_str}\\) 24h  _\\|  {vol} 24h vol  \\|  {oi} OI_")
        lines.append("")

    return "\n".join(lines)

# ------------ Send to Telegram ------------ #
def send_telegram_message(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "MarkdownV2",
        "disable_web_page_preview": True,
    }
    response = requests.post(url, json=payload)
    print(response.status_code, response.text)

# ------------ Entry Point ------------ #
def run_all():
    whitelist = load_whitelist()
    contracts = fetch_contracts(whitelist)
    if not contracts:
        print("No contracts fetched — nothing to send.")
        return
    text = format_digest(contracts)
    send_telegram_message(text)

if __name__ == "__main__":
    run_all()
