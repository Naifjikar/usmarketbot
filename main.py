import os, time, json, re, threading, traceback, hashlib
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from flask import Flask
from telegram import Bot

# ترجمة (قد تعلق) -> بنغلفها بمهلة
from deep_translator import GoogleTranslator
import concurrent.futures

# ================= CONFIG =================
TOKEN = os.getenv("TOKEN", "PUT_YOUR_TELEGRAM_TOKEN_HERE")
CHANNEL = os.getenv("CHANNEL", "@USMarketnow")
BENZINGA_KEY = os.getenv("BENZINGA_KEY", "PUT_YOUR_BENZINGA_KEY_HERE")

NEWS_INTERVAL_SEC = int(os.getenv("NEWS_INTERVAL_SEC", "60"))
ECON_INTERVAL_SEC = int(os.getenv("ECON_INTERVAL_SEC", "90"))

MAX_NEWS_PULL = int(os.getenv("MAX_NEWS_PULL", "50"))
MAX_TICKERS_PER_NEWS = int(os.getenv("MAX_TICKERS_PER_NEWS", "8"))

STATE_FILE = os.getenv("STATE_FILE", "news_state.json")
DEBUG = os.getenv("DEBUG", "1") == "1"

SCORE_THRESHOLD = int(os.getenv("SCORE_THRESHOLD", "3"))
TRANSLATE_ENABLED = os.getenv("TRANSLATE_ENABLED", "1") == "1"
TRANSLATE_TIMEOUT_SEC = int(os.getenv("TRANSLATE_TIMEOUT_SEC", "4"))

TZ_RIYADH = ZoneInfo("Asia/Riyadh")
TZ_UTC = ZoneInfo("UTC")

FOOTER = (
    "\n\nتابعنا لمتابعة الاخبار اللحظية\n"
    "⚠️ البورصة الامريكية | عاجل\n"
    "https://t.me/USMarketnow"
)

# ================= FILTERS =================
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

STRONG_KEYWORDS = {
    "fda": 3, "approval": 3, "cleared": 2,
    "phase 1": 3, "phase 2": 3, "phase 3": 4,
    "clinical trial": 4, "trial results": 4,
    "positive results": 3, "breakthrough": 3,
    "patent": 2,
    "acquisition": 4, "acquires": 4, "to acquire": 4,
    "merger": 4, "merges": 4,
    "definitive agreement": 4,
    "contract award": 4, "awarded": 3, "award": 3,
    "strategic partnership": 3, "partnership": 3,
    "earnings": 3, "eps": 4, "revenue": 3,
    "guidance": 4, "raises guidance": 5, "cuts guidance": 4,
    "beats": 4, "misses": 4,
    "launch": 2, "launches": 2,
    "new product": 3, "platform": 2,
    "artificial intelligence": 2, "ai": 2,
    "stock split": 4, "reverse split": 4,
    "buyback": 3, "share repurchase": 3
}

MACRO_KEYWORDS = [
    "federal reserve", "fed", "fomc", "powell", "interest rate", "rate decision",
    "cpi", "inflation", "ppi", "jobs report", "nonfarm", "nfp",
    "unemployment", "gdp", "retail sales", "ism", "pmi", "core inflation",
    "treasury", "yield", "bond yields"
]

# ================= INIT =================
if TOKEN.startswith("PUT_") or BENZINGA_KEY.startswith("PUT_"):
    # لا نكسر التشغيل، لكن ننبه باللوق
    print("⚠️ WARNING: TOKEN/BENZINGA_KEY placeholders detected. Set env vars TOKEN and BENZINGA_KEY.")

bot = Bot(token=TOKEN)

# translator can hang -> wrap with executor + timeout
translator = GoogleTranslator(source="auto", target="ar")
_translate_pool = concurrent.futures.ThreadPoolExecutor(max_workers=2)

# ================= HTTP SESSION with RETRIES =================
session = requests.Session()
retry = Retry(
    total=5,
    backoff_factor=0.8,
    status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=["GET", "POST"]
)
adapter = HTTPAdapter(max_retries=retry, pool_connections=20, pool_maxsize=20)
session.mount("http://", adapter)
session.mount("https://", adapter)

# ================= STATE (safe + atomic) =================
default_state = {
    "sent_news_ids": {},
    "sent_macro_uids": {},
    "econ_last_updated": 0,
    "sent_econ_uids": {},
}

_state_lock = threading.Lock()

def _now_ts():
    return int(time.time())

def _atomic_write_json(path: str, obj: dict):
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)

def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return default_state.copy()
    return default_state.copy()

state = load_state()

def save_state():
    with _state_lock:
        cutoff = _now_ts() - 30 * 24 * 3600
        for k in ("sent_news_ids", "sent_macro_uids", "sent_econ_uids"):
            state[k] = {kk: vv for kk, vv in state.get(k, {}).items() if vv >= cutoff}
        _atomic_write_json(STATE_FILE, state)

# ================= HELPERS =================
def safe_translate(text: str) -> str:
    text = (text or "").strip()
    if not text:
        return ""
    if not TRANSLATE_ENABLED:
        return text

    def _do():
        return translator.translate(text)

    try:
        fut = _translate_pool.submit(_do)
        return fut.result(timeout=TRANSLATE_TIMEOUT_SEC)  # يمنع التعليق
    except Exception:
        return text  # fallback

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

def safe_send(text: str):
    # Telegram send with retry protection
    for attempt in range(4):
        try:
            bot.send_message(chat_id=CHANNEL, text=text, disable_web_page_preview=True)
            return True
        except Exception as e:
            if DEBUG:
                print("❌ TG SEND ERROR:", repr(e))
            time.sleep(1.5 * (attempt + 1))
    return False

def make_fallback_id(it: dict) -> str:
    created = str(it.get("created") or it.get("updated") or "").strip()
    title = (it.get("title") or "").strip().lower()
    raw = f"{title}|{created}"
    return "tp:" + hashlib.sha1(raw.encode("utf-8")).hexdigest()

# ================= BENZINGA NEWS =================
def fetch_benzinga_news():
    url = "https://api.benzinga.com/api/v2/news"
    params = {
        "token": BENZINGA_KEY,
        "pageSize": MAX_NEWS_PULL,
        "sort": "created:desc",
    }
    r = session.get(url, params=params, timeout=20)
    r.raise_for_status()
    data = r.json()
    if isinstance(data, dict) and "data" in data:
        return data.get("data") or []
    if isinstance(data, list):
        return data
    return []

def extract_tickers(item: dict):
    stocks = item.get("stocks") or []
    tickers = []
    for s in stocks[:MAX_TICKERS_PER_NEWS]:
        sym = (s.get("symbol") or "").upper().strip()
        if sym and re.match(r"^[A-Z.\-]{1,10}$", sym):
            tickers.append(sym)

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
                news_id = str(it.get("id") or "").strip() or make_fallback_id(it)

                with _state_lock:
                    if news_id in state.get("sent_news_ids", {}):
                        continue

                title_en = (it.get("title") or "").strip()
                teaser_en = (it.get("teaser") or it.get("body") or "").strip()
                url = it.get("url") or it.get("link")

                if not title_en:
                    with _state_lock:
                        state["sent_news_ids"][news_id] = _now_ts()
                    continue

                lower_text = f"{title_en.lower()} {teaser_en.lower()}"
                if any(b in lower_text for b in BLOCK_KEYWORDS):
                    with _state_lock:
                        state["sent_news_ids"][news_id] = _now_ts()
                    continue

                title_ar = safe_translate(title_en)
                if is_buy_question(title_en, title_ar) or is_weak(title_en, title_ar):
                    with _state_lock:
                        state["sent_news_ids"][news_id] = _now_ts()
                    continue

                tickers = extract_tickers(it)
                sc = score_news(title_en, teaser_en)

                # Macro urgent
                if looks_macro(title_en, teaser_en):
                    macro_uid = f"macro:{news_id}"
                    with _state_lock:
                        already = macro_uid in state.get("sent_macro_uids", {})
                    if not already:
                        msg = format_macro_news_message(title_en, teaser_en, url=url)
                        if safe_send(msg):
                            with _state_lock:
                                state["sent_macro_uids"][macro_uid] = _now_ts()
                            save_state()
                            if DEBUG:
                                print("🚨 SENT MACRO:", title_en[:120])

                # Stock important only
                if sc < SCORE_THRESHOLD:
                    with _state_lock:
                        state["sent_news_ids"][news_id] = _now_ts()
                    continue

                if not tickers:
                    with _state_lock:
                        state["sent_news_ids"][news_id] = _now_ts()
                    continue

                msg = format_stock_news_message(title_en, teaser_en, tickers, url=url)
                if safe_send(msg):
                    with _state_lock:
                        state["sent_news_ids"][news_id] = _now_ts()
                    save_state()

                    if DEBUG:
                        print(f"✅ SENT NEWS [{sc}] {tickers[:3]} | {title_en[:120]}")

                time.sleep(2.5)

        except Exception as e:
            print("❌ NEWS ERROR:", repr(e))
            traceback.print_exc()

        time.sleep(NEWS_INTERVAL_SEC)

# ================= ECONOMIC CALENDAR =================
def fetch_econ_calendar(updated_ts: int):
    url = "https://api.benzinga.com/api/v2/calendar/economics"
    params = {"token": BENZINGA_KEY, "pagesize": 200}

    if updated_ts and updated_ts > 0:
        params["parameters[updated]"] = updated_ts

    today = datetime.now(TZ_RIYADH).date()
    params["parameters[date_from]"] = (today - timedelta(days=1)).strftime("%Y-%m-%d")
    params["parameters[date_to]"] = (today + timedelta(days=1)).strftime("%Y-%m-%d")

    r = session.get(url, params=params, timeout=20)
    r.raise_for_status()
    data = r.json()

    if isinstance(data, dict):
        for key in ("economics", "data", "events"):
            if key in data and isinstance(data[key], list):
                return data[key]
    if isinstance(data, list):
        return data
    return []

def impact_to_stars(importance: int) -> str:
    try:
        imp = int(importance)
    except Exception:
        imp = 2
    if imp <= 1:
        return "⭐️"
    if imp <= 3:
        return "⭐️⭐️"
    return "⭐️⭐️⭐️"

def parse_event_time(evt: dict) -> str:
    date_str = str(evt.get("date") or "").strip()
    time_str = str(evt.get("time") or "").strip()
    if date_str:
        try:
            if time_str:
                dt = datetime.fromisoformat(f"{date_str} {time_str}").replace(tzinfo=TZ_UTC)
            else:
                dt = datetime.fromisoformat(date_str).replace(tzinfo=TZ_UTC)
            return dt.astimezone(TZ_RIYADH).strftime("%Y-%m-%d %H:%M")
        except Exception:
            pass

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
    eid = str(evt.get("id") or "").strip()
    if eid:
        return f"econ:{eid}"
    raw = f"{evt.get('date','')}_{evt.get('time','')}_{evt.get('event','')}_{evt.get('country','')}"
    return "econ:" + hashlib.sha1(raw.encode("utf-8")).hexdigest()

def format_econ_message(evt: dict) -> str:
    event_name = (evt.get("event") or evt.get("name") or "").strip()
    country = (evt.get("country") or "US").strip()
    importance = evt.get("importance")
    stars = impact_to_stars(importance)

    actual = evt.get("actual")
    forecast = evt.get("forecast")
    previous = evt.get("previous")

    tstamp = parse_event_time(evt)
    event_ar = safe_translate(event_name) if event_name else "حدث اقتصادي"

    lines = []
    lines.append(f"🚨 تقويم اقتصادي 🇺🇸 ({stars})")
    lines.append(f"\nالحدث:\n{event_ar}")
    lines.append(f"\nالوقت:\n{tstamp} (بتوقيت السعودية)")
    lines.append(f"\nالأهمية:\n{stars}")
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
            with _state_lock:
                updated_ts = int(state.get("econ_last_updated", 0) or 0)

            if DEBUG:
                print(f"✅ ECON tick: {datetime.now(TZ_RIYADH).strftime('%Y-%m-%d %H:%M:%S')} | updated>={updated_ts}")

            events = fetch_econ_calendar(updated_ts)
            max_seen_updated = updated_ts

            for evt in events:
                uid = econ_uid(evt)
                with _state_lock:
                    if uid in state.get("sent_econ_uids", {}):
                        continue

                country = (evt.get("country") or "").upper().strip()
                if country and country not in ("US", "USA", "UNITED STATES"):
                    continue

                try:
                    imp = int(evt.get("importance")) if evt.get("importance") is not None else 2
                except Exception:
                    imp = 2

                # فقط متوسط فأعلى
                if imp <= 1:
                    continue

                msg = format_econ_message(evt)
                if safe_send(msg):
                    with _state_lock:
                        state["sent_econ_uids"][uid] = _now_ts()

                    upd = evt.get("updated")
                    if isinstance(upd, (int, float)) and int(upd) > max_seen_updated:
                        max_seen_updated = int(upd)

                    save_state()
                    if DEBUG:
                        name = (evt.get("event") or evt.get("name") or "")[:80]
                        print(f"📅 SENT ECON [{imp}] {name}")

                time.sleep(2.5)

            if max_seen_updated > updated_ts:
                with _state_lock:
                    state["econ_last_updated"] = max_seen_updated
                save_state()

        except Exception as e:
            print("❌ ECON ERROR:", repr(e))
            traceback.print_exc()

        time.sleep(ECON_INTERVAL_SEC)

# ================= WATCHDOG =================
def start_daemon(name: str, target):
    t = threading.Thread(target=target, daemon=True, name=name)
    t.start()
    return t

def watchdog():
    global t_news, t_econ
    while True:
        try:
            if not t_news.is_alive():
                print("⚠️ NEWS thread died. Restarting...")
                t_news = start_daemon("news_loop", news_loop)
            if not t_econ.is_alive():
                print("⚠️ ECON thread died. Restarting...")
                t_econ = start_daemon("econ_loop", econ_loop)
        except Exception:
            traceback.print_exc()
        time.sleep(10)

# ================= FLASK =================
app = Flask(__name__)

@app.get("/")
def home():
    return "OK - USMarketNow NEWS bot is running"

@app.get("/health")
def health():
    return {"status": "ok", "ts": time.time()}

if __name__ == "__main__":
    t_news = start_daemon("news_loop", news_loop)
    t_econ = start_daemon("econ_loop", econ_loop)
    t_watch = start_daemon("watchdog", watchdog)

    port = int(os.getenv("PORT", "10000"))
    print(f"🌐 Starting web server on 0.0.0.0:{port}")
    app.run(host="0.0.0.0", port=port, threaded=True)
