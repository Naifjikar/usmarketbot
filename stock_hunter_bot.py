import os, time, requests, math
from datetime import datetime
from zoneinfo import ZoneInfo

# ================= CONFIG =================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
POLYGON_KEY = os.getenv("POLYGON_API_KEY")

INTERVAL = 120  # seconds
MAX_STOCKS = 3

PRICE_MIN = 1
PRICE_MAX = 10
MIN_VOLUME = 1_000_000
MIN_CHANGE_PCT = 10
MAX_FLOAT = 50_000_000
# ========================================

sent_today = set()

def tg_send(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": CHAT_ID, "text": text}, timeout=20)

def get_gainers():
    url = "https://api.polygon.io/v2/snapshot/locale/us/markets/stocks/gainers"
    r = requests.get(url, params={"apiKey": POLYGON_KEY}, timeout=20)
    r.raise_for_status()
    return r.json().get("tickers", [])

def get_float(ticker):
    url = f"https://api.polygon.io/v3/reference/tickers/{ticker}"
    r = requests.get(url, params={"apiKey": POLYGON_KEY}, timeout=20)
    if r.status_code != 200:
        return None
    return r.json().get("results", {}).get("share_class_shares_outstanding")

def calc_levels(entry):
    stop = round(entry * 0.91, 2)
    targets = [
        round(entry * 1.08, 2),
        round(entry * 1.15, 2),
        round(entry * 1.25, 2),
        round(entry * 1.40, 2),
    ]
    return stop, targets

def main():
    tz = ZoneInfo("Asia/Riyadh")
    tg_send("✅ Bot started – Stock Hunter MVP")

    while True:
        try:
            stocks = get_gainers()
            picks = []

            for s in stocks:
                t = s.get("ticker")
                if t in sent_today:
                    continue

                price = s.get("lastTrade", {}).get("p")
                vol = s.get("day", {}).get("v", 0)
                change_pct = s.get("todaysChangePerc", 0)

                if not price or price < PRICE_MIN or price > PRICE_MAX:
                    continue
                if vol < MIN_VOLUME or change_pct < MIN_CHANGE_PCT:
                    continue

                flt = get_float(t)
                if flt and flt > MAX_FLOAT:
                    continue

                entry = round(price, 2)
                stop, targets = calc_levels(entry)

                picks.append((t, entry, stop, targets))
                sent_today.add(t)

                if len(picks) >= MAX_STOCKS:
                    break

            for t, entry, stop, targets in picks:
                msg = (
                    f"{t}\n"
                    f"دخول: {entry}\n"
                    f"وقف: {stop}\n"
                    f"الأهداف:\n"
                    f"{targets[0]}\n{targets[1]}\n{targets[2]}\n{targets[3]}"
                )
                tg_send(msg)

        except Exception as e:
            tg_send(f"⚠️ Error: {e}")

        time.sleep(INTERVAL)

if __name__ == "__main__":
    if not TELEGRAM_TOKEN or not CHAT_ID or not POLYGON_KEY:
        raise SystemExit("❌ Missing env vars")
    main()
