import os, time, json, re, threading, traceback
import requests
from flask import Flask
from telegram import Bot
from deep_translator import GoogleTranslator
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

# ================= HARDCODED CONFIG (TEMP) =================
TOKEN = "PUT_YOUR_TELEGRAM_TOKEN_HERE"
CHANNEL = "@USMarketnow"
BENZINGA_KEY = "PUT_YOUR_BENZINGA_KEY_HERE"
# ==========================================================
# Polling intervals
NEWS_INTERVAL_SEC = int(os.getenv("NEWS_INTERVAL_SEC", "60"))
ECON_INTERVAL_SEC = int(os.getenv("ECON_INTERVAL_SEC", "60"))

# Limits
MAX_NEWS_PULL = int(os.getenv("MAX_NEWS_PULL", "50"))
MAX_TICKERS_PER_NEWS = int(os.getenv("MAX_TICKERS_PER_NEWS", "8"))

STATE_FILE = os.getenv("STATE_FILE", "news_state.json")
DEBUG = os.getenv("DEBUG", "1") == "1"

TZ_RIYADH = ZoneInfo("Asia/Riyadh")
TZ_UTC = ZoneInfo("UTC")

FOOTER = (
    "\n\nتابعنا لمتابعة الاخبار اللحظية\n"
    "⚠️ البورصة الامريكية | عاجل\n"
    "https://t.me/USMarketnow"
)

# ====== Filters: remove legal spam, fluff, "buy these stocks" ======
BLOCK_KEYWORDS = [
    "class action", "lawsuit", "law firm", "investors are encouraged",
    "deadline", "litigation", "rosen", "pomerantz", "glancy",
    "levi & korsinsky", "korsinsky", "investigation",
    "shareholder alert", "securities fraud"
]

WEAK_KEYWORDS = [
    "how to", "what is", "explained", "opinion", "analysis",
    "preview", "stocks to watch", "watchlist",
    "top", "best", "favorite", "picks",
    "to buy", "buy now", "buying now",
    "prediction", "forecast", "price target",
    "analyst", "rating", "ratings", "upgrade", "downgrade",
    "why you should", "here's", "this week", "these stocks",
    "undervalued", "overvalued",
    "buy the dip", "dip buy", "buy on weakness",
]

AR_WEAK = [
    "أفضل", "افضل", "للشراء", "شراء الآن", "للشراء الآن",
    "ترشيحات", "قائمة", "قوائم", "توصيات", "أسهم مفضلة",
    "أفضل أسهم", "افضل اسهم", "أسهم للشراء", "للشراء اليوم",
    "شراء الانخفاض", "فرصة شراء",
    "هل يجب", "هل عليك", "يجب عليك", "هل حان", "هل هذا", "هل ما زال"
]

QUESTION_BUY_PATTERNS_EN = [
    "should you buy", "should i buy", "is it time to buy", "is it a good time to buy"
]
QUESTION_BUY_PATTERNS_AR = [
    "هل يجب عليك شراء", "هل عليك شراء", "هل يجب شراء", "هل اشتري", "هل نشتري", "هل يجب"
]

# Strong scoring for stock news (headline/teaser)
STRONG_KEYWORDS = {
    # Pharma / FDA / Trials
    "fda": 3, "approval": 3, "cleared": 2,
    "phase 1": 3, "phase 2": 3, "phase 3": 4,
    "clinical trial": 4, "trial results": 4,
    "positive results": 3, "breakthrough": 3,
    "patent": 2,

    # M&A / Deals
    "acquisition": 4, "acquires": 4, "to acquire": 4,
    "merger": 4, "merges": 4,
    "definitive agreement": 4,
    "contract award": 4, "awarded": 3, "award": 3,
    "strategic partnership": 3, "partnership": 3,

    # Earnings / Guidance
    "earnings": 3, "eps": 4, "revenue": 3,
    "guidance": 4, "raises guidance": 5, "cuts guidance": 4,
    "beats": 4, "misses": 4,

    # Product / Tech
    "launch": 2, "launches": 2,
    "new product": 3, "platform": 2,
    "artificial intelligence": 2, "ai": 2,

    # Capital actions
    "stock split": 4, "reverse split": 4,
    "buyback": 3, "share repurchase": 3
}

SCORE_THRESHOLD = int(os.getenv("SCORE_THRESHOLD", "3"))

# Macro keywords (Fed / high-impact US releases)
MACRO_KEYWORDS = [
    "federal reserve", "fed", "fomc", "powell", "interest rate", "rate decision",
    "cpi", "inflation", "ppi", "jobs report", "nonfarm", "nfp",
    "unemployment", "gdp", "retail sales", "ism", "pmi", "core inflation",
    "treasury", "yield", "bond yields"
]

# ================= INIT =================
if not TOKEN or not BENZINGA_KEY:
    raise RuntimeError("Missing env vars: TOKEN and BENZINGA_KEY are required.")

bot = Bot(token=TOKEN)
translator = GoogleTranslator(source="auto", target="ar")
session = requests.Session()

# ================= STATE =================
default_state = {
    "sent_news_ids": {},       # news_id -> ts
    "sent_macro_uids": {},     # macro uid -> ts
    "econ_last_updated": 0,    # unix ts (UTC) for incremental fetch
    "sent_econ_uids": {},      # econ uid -> ts
}

if os.path.exists(STATE_FILE):
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            state = json.load(f)
    except Exception:
        state = default_state
else:
    state = default_state

def _now_ts():
    return int(time.time())

def save_state():
    cutoff = _now_ts() - 30 * 24 * 3600
    state["sent_news_ids"] = {k: v for k, v in state.get("sent_news_ids", {}).items() if v >= cutoff}
    state["sent_macro_uids"] = {k: v for k, v in state.get("sent_macro_uids", {}).items() if v >= cutoff}
    state["sent_econ_uids"] = {k: v for k, v in state.get("sent_econ_uids", {}).items() if v >= cutoff}
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def safe_translate(text: str) -> str:
    text = (text or "").strip()
    if not text:
        return ""
    try:
        return translator.translate(text)
    except Exception:
        return text

def is_weak(title_en: str, title_ar: str) -> bool:
    t = (title_en or "").lower()
    if any(w in t for w in WEAK_KEYWORDS):
        return True
    a = title_ar or ""
    if any(w in a for w in AR_WEAK):
        return True
    return False

def is_buy_question(title_en: str, title_ar: str) -> bool:
    t = (title_en or "").lower()
    a = title_ar or ""
    if any(p in t for p in QUESTION_BUY_PATTERNS_EN):
        return True
    if any(p in a for p in QUESTION_BUY_PATTERNS_AR):
        return True
    return False

def score_news(title: str, desc: str = "") -> int:
    text = f"{(title or '').lower()} {(desc or '').lower()}"
    if any(b in text for b in BLOCK_KEYWORDS):
        return 0
    if any(w in text for w in WEAK_KEYWORDS):
        return 0
    s = 0
    for k, pts in STRONG_KEYWORDS.items():
        if k in text:
            s += pts
    return s

def looks_macro(title: str, desc: str) -> bool:
    text = f"{(title or '').lower()} {(desc or '').lower()}"
    return any(k in text for k in MACRO_KEYWORDS)

# ================= BENZINGA NEWS =================
def fetch_benzinga_news():
    url = "https://api.benzinga.com/api/v2/news"
    params = {
        "token": BENZINGA_KEY,
        "pageSize": MAX_NEWS_PULL,
        "sort": "created:desc",
    }
    r = session.get(url, params=params, timeout=25)
    r.raise_for_status()
    data = r.json()
    if isinstance(data, dict) and "data" in data:
        return data.get("data") or []
    if isinstance(data, list):
        return data
    return []

def extract_tickers(item: dict):
    # Benzinga often returns stocks list with {"symbol": "..."}
    stocks = item.get("stocks") or []
    tickers = []
    for s in stocks[:MAX_TICKERS_PER_NEWS]:
        sym = (s.get("symbol") or "").upper().strip()
        if sym and re.match(r"^[A-Z.\-]{1,10}$", sym):
            tickers.append(sym)
    # fallback (some payloads have "symbols" or similar)
    if not tickers:
        syms = item.get("symbols") or []
        for sym in syms[:MAX_TICKERS_PER_NEWS]:
            sym = str(sym).upper().strip()
            if sym and re.match(r"^[A-Z.\-]{1,10}$", sym):
                tickers.append(sym)
    return tickers

def format_stock_news_message(title_en, teaser_en, tickers, url=None):
    title_ar = safe_translate(title_en)
    teaser_ar = safe_translate(teaser_en) if teaser_en else ""
    tickers_str = ", ".join(tickers[:8]) if tickers else "—"
    link_line = f"\n\nرابط:\n{url}" if url else ""
    return (
        f"خبر:\n{title_ar}\n\n"
        f"رمز السهم:\n{tickers_str}\n\n"
        f"تفاصيل الخبر:\n{teaser_ar}"
        f"{link_line}"
        f"{FOOTER}"
    )

def format_macro_news_message(title_en, teaser_en, url=None):
    title_ar = safe_translate(title_en)
    teaser_ar = safe_translate(teaser_en) if teaser_en else ""
    link_line = f"\n\nرابط:\n{url}" if url else ""
    return (
        f"🚨 عاجل (اقتصاد/فيدرالي)\n\n"
        f"{title_ar}\n\n"
        f"{teaser_ar}"
        f"{link_line}"
        f"{FOOTER}"
    )

def news_loop():
    while True:
        try:
            if DEBUG:
                print(f"✅ NEWS tick: {datetime.now(TZ_RIYADH).strftime('%Y-%m-%d %H:%M:%S')}")
            items = fetch_benzinga_news()

            for it in items:
                news_id = str(it.get("id") or "").strip()
                if not news_id:
                    # fallback uid: title+created
                    created = str(it.get("created") or it.get("updated") or "").strip()
                    title = (it.get("title") or "").strip().lower()
                    news_id = f"tp:{title}|{created}"

                if news_id in state.get("sent_news_ids", {}):
                    continue

                title_en = (it.get("title") or "").strip()
                teaser_en = (it.get("teaser") or it.get("body") or "").strip()
                url = it.get("url") or it.get("link")

                # Basic blocks
                if not title_en:
                    state["sent_news_ids"][news_id] = _now_ts()
                    continue

                lower_text = f"{title_en.lower()} {teaser_en.lower()}"
                if any(b in lower_text for b in BLOCK_KEYWORDS):
                    state["sent_news_ids"][news_id] = _now_ts()
                    continue

                title_ar = safe_translate(title_en)
                if is_buy_question(title_en, title_ar) or is_weak(title_en, title_ar):
                    state["sent_news_ids"][news_id] = _now_ts()
                    continue

                tickers = extract_tickers(it)
                sc = score_news(title_en, teaser_en)

                # Macro urgent (even if no tickers)
                if looks_macro(title_en, teaser_en):
                    macro_uid = f"macro:{news_id}"
                    if macro_uid not in state.get("sent_macro_uids", {}):
                        msg = format_macro_news_message(title_en, teaser_en, url=url)
                        bot.send_message(chat_id=CHANNEL, text=msg, disable_web_page_preview=True)
                        state["sent_macro_uids"][macro_uid] = _now_ts()
                        if DEBUG:
                            print("🚨 SENT MACRO:", title_en[:120])
                        save_state()

                # Stock important only
                if sc < SCORE_THRESHOLD:
                    state["sent_news_ids"][news_id] = _now_ts()
                    continue

                # require tickers for stock-news messages
                if not tickers:
                    state["sent_news_ids"][news_id] = _now_ts()
                    continue

                msg = format_stock_news_message(title_en, teaser_en, tickers, url=url)
                bot.send_message(chat_id=CHANNEL, text=msg, disable_web_page_preview=True)

                state["sent_news_ids"][news_id] = _now_ts()
                save_state()

                if DEBUG:
                    print(f"✅ SENT NEWS [{sc}] {tickers[:3]} | {title_en[:120]}")

                time.sleep(5)  # تهدئة بسيطة بين الإرسال

        except Exception as e:
            print("❌ NEWS ERROR:", repr(e))
            traceback.print_exc()

        time.sleep(NEWS_INTERVAL_SEC)

# ================= ECONOMIC CALENDAR (3 levels) =================
# Benzinga endpoint: /api/v2/calendar/economics (supports parameters[importance], parameters[updated], date_from/date_to)
# Docs mention Impact Level low/medium/high.  [oai_citation:0‡docs.benzinga.com](https://docs.benzinga.com/benzinga-apis/calendar/get-economics?utm_source=chatgpt.com)

def fetch_econ_calendar(updated_ts: int):
    url = "https://api.benzinga.com/api/v2/calendar/economics"
    params = {
        "token": BENZINGA_KEY,
        "pagesize": 200,
    }
    # incremental fetch by updated timestamp (UTC unix)
    if updated_ts and updated_ts > 0:
        params["parameters[updated]"] = updated_ts

    # also limit to a reasonable date window (today +/- 1 day) to avoid huge payloads
    today = datetime.now(TZ_RIYADH).date()
    date_from = (today - timedelta(days=1)).strftime("%Y-%m-%d")
    date_to = (today + timedelta(days=1)).strftime("%Y-%m-%d")
    params["parameters[date_from]"] = date_from
    params["parameters[date_to]"] = date_to

    r = session.get(url, params=params, timeout=25)
    r.raise_for_status()
    data = r.json()

    # typical shape: {"economics":[...]} or {"data":[...]} depending on version
    if isinstance(data, dict):
        for key in ("economics", "data", "events"):
            if key in data and isinstance(data[key], list):
                return data[key]
    if isinstance(data, list):
        return data
    return []

def impact_to_stars(importance: int) -> str:
    # Benzinga calendar importance is integer; impact described as low/medium/high.  [oai_citation:1‡benzinga.com](https://www.benzinga.com/apis/cloud-product/economic_calendar/)
    # We map into 3 levels:
    # 0-1 -> low, 2-3 -> medium, 4-5 -> high (conservative)
    if importance is None:
        return "⭐️⭐️"  # default medium
    try:
        imp = int(importance)
    except Exception:
        return "⭐️⭐️"
    if imp <= 1:
        return "⭐️"
    if imp <= 3:
        return "⭐️⭐️"
    return "⭐️⭐️⭐️"

def parse_event_time(evt: dict) -> str:
    # fields vary: date + time, or timestamp
    date_str = str(evt.get("date") or "").strip()
    time_str = str(evt.get("time") or "").strip()  # may be HH:MM:SS
    if date_str:
        try:
            if time_str:
                dt = datetime.fromisoformat(f"{date_str} {time_str}").replace(tzinfo=TZ_UTC)
            else:
                dt = datetime.fromisoformat(date_str).replace(tzinfo=TZ_UTC)
            return dt.astimezone(TZ_RIYADH).strftime("%Y-%m-%d %H:%M")
        except Exception:
            pass

    # fallback: unix timestamp fields
    for k in ("timestamp", "time_unix", "updated", "created"):
        v = evt.get(k)
        if isinstance(v, (int, float)) and v > 0:
            try:
                dt = datetime.fromtimestamp(int(v), tz=TZ_UTC).astimezone(TZ_RIYADH)
                return dt.strftime("%Y-%m-%d %H:%M")
            except Exception:
                continue
    return datetime.now(TZ_RIYADH).strftime("%Y-%m-%d %H:%M")

def econ_uid(evt: dict) -> str:
    # stable uid
    eid = str(evt.get("id") or "").strip()
    if eid:
        return f"econ:{eid}"
    # fallback
    return f"econ:{evt.get('date','')}_{evt.get('time','')}_{evt.get('event','')}_{evt.get('country','')}"

def format_econ_message(evt: dict) -> str:
    event_name = (evt.get("event") or evt.get("name") or "").strip()
    country = (evt.get("country") or "US").strip()
    importance = evt.get("importance")
    stars = impact_to_stars(importance)

    actual = (evt.get("actual") or "").strip() if isinstance(evt.get("actual"), str) else evt.get("actual")
    forecast = (evt.get("forecast") or "").strip() if isinstance(evt.get("forecast"), str) else evt.get("forecast")
    previous = (evt.get("previous") or "").strip() if isinstance(evt.get("previous"), str) else evt.get("previous")

    tstamp = parse_event_time(evt)

    # ترجمة اسم الحدث للعربي (بشكل آمن)
    event_ar = safe_translate(event_name) if event_name else "حدث اقتصادي"

    lines = []
    lines.append(f"🚨 تقويم اقتصادي 🇺🇸 ({stars})")
    lines.append(f"\nالحدث:\n{event_ar}")
    lines.append(f"\nالوقت:\n{tstamp} (بتوقيت السعودية)")
    lines.append(f"\nالأهمية:\n{stars}  (منخفض/متوسط/عالي)")
    if actual not in (None, "", "None"):
        lines.append(f"\nالفعلي (Actual): {actual}")
    if forecast not in (None, "", "None"):
        lines.append(f"\nالمتوقع (Forecast): {forecast}")
    if previous not in (None, "", "None"):
        lines.append(f"\nالسابق (Previous): {previous}")

    return "\n".join(lines) + FOOTER

def econ_loop():
    while True:
        try:
            if DEBUG:
                print(f"✅ ECON tick: {datetime.now(TZ_RIYADH).strftime('%Y-%m-%d %H:%M:%S')} | updated>={state.get('econ_last_updated', 0)}")

            updated_ts = int(state.get("econ_last_updated", 0) or 0)
            events = fetch_econ_calendar(updated_ts)

            max_seen_updated = updated_ts

            for evt in events:
                uid = econ_uid(evt)
                if uid in state.get("sent_econ_uids", {}):
                    continue

                # country filter (focus on US / FED relevant)
                country = (evt.get("country") or "").upper().strip()
                if country and country not in ("US", "USA", "UNITED STATES"):
                    continue

                # only send medium/high by default (to avoid spam),
                # but keep 3 levels in message anyway.
                importance = evt.get("importance")
                try:
                    imp = int(importance) if importance is not None else 2
                except Exception:
                    imp = 2

                # هنا نرسل كل شيء "متوسط فأعلى"
                if imp <= 1:
                    continue

                msg = format_econ_message(evt)
                bot.send_message(chat_id=CHANNEL, text=msg, disable_web_page_preview=True)

                state["sent_econ_uids"][uid] = _now_ts()
                save_state()

                if DEBUG:
                    name = (evt.get("event") or evt.get("name") or "")[:80]
                    print(f"📅 SENT ECON [{imp}] {name}")

                time.sleep(5)

                # update max updated timestamp to advance incremental cursor
                upd = evt.get("updated")
                if isinstance(upd, (int, float)) and int(upd) > max_seen_updated:
                    max_seen_updated = int(upd)

            # bump cursor forward
            if max_seen_updated > updated_ts:
                state["econ_last_updated"] = max_seen_updated
                save_state()

        except Exception as e:
            print("❌ ECON ERROR:", repr(e))
            traceback.print_exc()

        time.sleep(ECON_INTERVAL_SEC)

# ================= FLASK SERVER (keeps Web Service alive) =================
app = Flask(__name__)

@app.get("/")
def home():
    return "OK - USMarketNow NEWS bot is running"

@app.get("/health")
def health():
    return {"status": "ok", "ts": time.time()}

if __name__ == "__main__":
    # threads
    t1 = threading.Thread(target=news_loop, daemon=True)
    t2 = threading.Thread(target=econ_loop, daemon=True)
    t1.start()
    t2.start()

    port = int(os.getenv("PORT", "10000"))
    print(f"🌐 Starting web server on 0.0.0.0:{port}")
    app.run(host="0.0.0.0", port=port)
