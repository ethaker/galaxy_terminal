import json
import boto3
import requests
from datetime import datetime, timezone

S3_BUCKET = "galaxy-terminal-config"
S3_KEY = "whitelist.json"
BOT_TOKEN = "8819186886:AAHQnJWYoU98thFHXXgn407rAJZUbuB6xaY"
GAMMA_BASE = "https://gamma-api.polymarket.com"


def load_whitelist():
    s3 = boto3.client("s3")
    try:
        obj = s3.get_object(Bucket=S3_BUCKET, Key=S3_KEY)
        return json.loads(obj["Body"].read().decode("utf-8"))
    except s3.exceptions.NoSuchKey:
        return []


def save_whitelist(entries):
    s3 = boto3.client("s3")
    s3.put_object(
        Bucket=S3_BUCKET,
        Key=S3_KEY,
        Body=json.dumps(entries, indent=2).encode("utf-8"),
        ContentType="application/json",
    )


def extract_slug(url):
    # Handles https://polymarket.com/event/some-slug or just some-slug
    url = url.strip().rstrip("/")
    if "polymarket.com/event/" in url:
        return url.split("polymarket.com/event/")[-1]
    return url


def resolve_market(slug):
    resp = requests.get(f"{GAMMA_BASE}/events", params={"slug": slug})
    resp.raise_for_status()
    data = resp.json()
    if not data:
        return None, None
    event = data[0]
    markets = event.get("markets", [])
    if not markets:
        return None, None
    # Pick market with highest YES odds
    best = max(markets, key=lambda m: float((json.loads(m.get("outcomePrices") or "[0]"))[0]))
    return best.get("conditionId"), event.get("title", slug)


def md_escape(text):
    for ch in r"\_*[]()~`>#+-=|{}.!":
        text = str(text).replace(ch, f"\\{ch}")
    return text


def reply(chat_id, text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    r = requests.post(url, json={
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "MarkdownV2",
        "disable_web_page_preview": True,
    })
    print(f"TG reply: {r.status_code} {r.text}")


def handle_add(chat_id, args):
    if not args:
        reply(chat_id, "Usage: `/add <polymarket url>`")
        return

    slug = extract_slug(args[0])
    whitelist = load_whitelist()

    if any(e["slug"] == slug for e in whitelist):
        reply(chat_id, f"Already tracking that market")
        return

    condition_id, title = resolve_market(slug)
    if not condition_id:
        reply(chat_id, f"Could not resolve market for `{slug}` — check the URL and try again")
        return

    whitelist.append({
        "slug": slug,
        "condition_id": condition_id,
        "title": title,
        "added_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    })
    save_whitelist(whitelist)
    reply(chat_id, f"Added: *{md_escape(title)}*")


def handle_remove(chat_id, args):
    if not args:
        reply(chat_id, "Usage: `/remove <polymarket url>`")
        return

    slug = extract_slug(args[0])
    whitelist = load_whitelist()
    updated = [e for e in whitelist if e["slug"] != slug]

    if len(updated) == len(whitelist):
        reply(chat_id, "That market isn't on the watchlist")
        return

    save_whitelist(updated)
    reply(chat_id, f"Removed from whitelist")


def handle_thresholds(chat_id):
    reply(chat_id, (
        "*Alert thresholds:*\n\n"
        "• >$10M lifetime vol — move \\>2\\.5%\n"
        "• $1M–$10M lifetime vol — move \\>3\\.5%\n"
        "• $100k–$1M lifetime vol — move \\>4\\.0%\n"
        "• <$100k — no alerts"
    ))


def handle_list(chat_id):
    whitelist = load_whitelist()
    if not whitelist:
        reply(chat_id, "Whitelist is empty")
        return
    lines = [f"*Current whitelist \\({len(whitelist)} markets\\):*", ""]
    for e in whitelist:
        url = f"https://polymarket\\.com/event/{e['slug']}"
        lines.append(f"• [{md_escape(e['title'])}]({url})")
    reply(chat_id, "\n".join(lines))


def lambda_handler(event, context):
    try:
        body = json.loads(event.get("body") or "{}")
        message = body.get("message", {})
        chat_id = message.get("chat", {}).get("id")
        text = message.get("text", "").strip()

        if not chat_id or not text:
            return {"statusCode": 200, "body": "ok"}

        parts = text.split()
        command = parts[0].lower().split("@")[0]
        args = parts[1:]

        if command == "/add":
            handle_add(chat_id, args)
        elif command == "/remove":
            handle_remove(chat_id, args)
        elif command == "/list":
            handle_list(chat_id)
        elif command == "/thresholds":
            handle_thresholds(chat_id)

    except Exception as e:
        print(f"Error: {e}")

    return {"statusCode": 200, "body": "ok"}
