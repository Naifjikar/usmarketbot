import os, time, requests
from datetime import datetime
from zoneinfo import ZoneInfo

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")      # توكن بوت تيليجرام
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")          # ايدي القناة/القروب/الشات
POLYGON_KEY = os.getenv("POLYGON_API_KEY")       # مفتاح Polygon

INTERVAL_SEC = int(os.getenv("INTERVAL_SEC", "120"))
TICKERS = [t.strip().upper() for t in os.getenv("TICKERS", "AAPL,TSLA").split(",") if t.strip()]

def tg_send(text: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    r = requests.post(url, json={"chat_id": CHAT_ID, "text": text, "disable_web_page_preview": True}, timeout=20)
    r.raise_for_status()

def polygon_last_price(ticker: str):
    # last trade endpoint
    url = f"https://api.polygon.io/v2/last/trade/{ticker}"
    r = requests.get(url, params={"apiKey": POLYGON_KEY}, timeout=20)
    r.raise_for_status()
    data = r.json()
    # بعض الحسابات ترجع last.trade.p
    return data.get("results", {}).get("p")

def main():
    tz = ZoneInfo("Asia/Riyadh")
    tg_send("✅ Stage 1 started: symbol + price فقط")
    while True:
        now = datetime.now(tz).strftime("%Y-%m-%d %H:%M")
        lines = [f"⏱ {now} (KSA)"]
        for t in TICKERS:
            try:
                p = polygon_last_price(t)
                if p is None:
                    lines.append(f"{t} - N/A")
                else:
                    lines.append(f"{t} - {p}")
            except Exception:
                lines.append(f"{t} - ERR")
        tg_send("\n".join(lines))
        time.sleep(INTERVAL_SEC)

if __name__ == "__main__":
    missing = [k for k,v in {
        "TELEGRAM_TOKEN": TELEGRAM_TOKEN,
        "TELEGRAM_CHAT_ID": CHAT_ID,
        "POLYGON_API_KEY": POLYGON_KEY
    }.items() if not v]
    if missing:
        raise SystemExit(f"Missing env vars: {', '.join(missing)}")
    main()
