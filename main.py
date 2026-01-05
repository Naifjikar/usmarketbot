import os, time, json, re, threading, traceback
import requests
from flask import Flask
from telegram import Bot
from deep_translator import GoogleTranslator

# ================= CONFIG =================
TOKEN = os.getenv("TOKEN", "8101036051:AAEMbhWIYv22FOMV6pXcAOosEWxsy9v3jfY")
CHANNEL = os.getenv("CHANNEL", "@USMarketnow")
POLYGON_KEY = os.getenv("POLYGON_KEY", "ht3apHm7nJA2VhvBynMHEcpRI11VSRbq")

PRICE_MIN, PRICE_MAX = 0.01, 10.0
INTERVAL = 60
MAX_NEWS = 120
MAX_TICKERS_PER_NEWS = 12
STATE_FILE = "news_state.json"

SCORE_THRESHOLD = 3
DEBUG = True

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
    # علاج / أبحاث
    "fda": 3, "approval": 3, "cleared": 2,
    "phase 1": 3, "phase 2": 3, "phase 3": 4,
    "clinical trial": 4, "trial results": 4,
    "positive results": 3, "breakthrough": 3,
    "patent": 2,

    # استحواذ / صفقات
    "acquisition": 4, "acquires": 4, "to acquire": 4,
    "merger": 4, "merges": 4,
    "definitive agreement": 4,
    "contract": 3, "agreement": 2,
    "strategic partnership": 3,
    "award": 3, "awarded": 3, "contract award": 4,

    # أرباح / نتائج
    "earnings": 3, "eps": 4, "revenue": 3,
    "guidance": 4, "raises guidance": 5, "cuts guidance": 4,
    "beats": 4, "misses": 4,
    "profit": 3, "net income": 3,

    # تقنية / إطلاق
    "launch": 2, "launches": 2,
    "new product": 3, "platform": 2,
    "chip": 2, "cybersecurity": 2,
    "artificial intelligence": 2, "ai": 2,

    # أخرى قوية
    "buyback": 3, "share repurchase": 3,
    "stock split": 4, "reverse split": 4
}

# ================= INIT =================
bot = Bot(token=TOKEN)
translator = GoogleTranslator(source="auto", target="ar")
session = requests.Session()

if os.path.exists(STATE_FILE):
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            state = json.load(f)
    except Exception:
        state = {}
else:
    state = {}

def save_state():
    cutoff = time.time() - 30 * 24 * 3600
    compact = {k: v for k, v in state.items() if v >= cutoff}
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(compact, f, ensure_ascii=False, indent=2)

def make_uid(n: dict) -> str:
    nid = str(n.get("id") or "").strip()
    if nid:
        return f"id:{nid}"
    title = (n.get("title") or "").strip().lower()
    pub = (n.get("published_utc") or "").strip()
    return f"tp:{title}|{pub}"

def pg(path, params=None):
    params = params or {}
    params["apiKey"] = POLYGON_KEY
    r = session.get("https://api.polygon.io" + path, params=params, timeout=25)
    r.raise_for_status()
    return r.json()

_price_cache = {}  # sym -> (price, ts)

def get_price(sym: str):
    sym = sym.upper().strip()
    now = time.time()
    if sym in _price_cache and now - _price_cache[sym][1] < 60:
        return _price_cache[sym][0]
    try:
        snap = pg(f"/v2/snapshot/locale/us/markets/stocks/tickers/{sym}")
        p = snap.get("ticker", {}).get("day", {}).get("c")
        if p is None:
            p = snap.get("ticker", {}).get("lastTrade", {}).get("p")
        if p is None:
            return None
        p = float(p)
        if p <= 0:
            return None
        _price_cache[sym] = (p, now)
        return p
    except Exception:
        return None

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
    if any(w in text for w in WEAK_KEYWORDS):
        return 0
    s = 0
    for k, pts in STRONG_KEYWORDS.items():
        if k in text:
            s += pts
    return s

# ================= BOT LOOP (Background Thread) =================
def bot_loop():
    while True:
        try:
            if DEBUG:
                print(f"✅ Tick alive: {time.strftime('%Y-%m-%d %H:%M:%S')} | fetching news...")

            counters = {
                "fetched": 0, "sent": 0, "dup": 0, "blocked_legal": 0,
                "buy_question": 0, "weak": 0, "score_low": 0,
                "no_tickers": 0, "price_out_or_none": 0
            }

            news = pg("/v2/reference/news", {
                "limit": MAX_NEWS,
                "order": "desc",
                "sort": "published_utc"
            }).get("results", []) or []

            counters["fetched"] = len(news)
            if DEBUG:
                print(f"📰 fetched: {len(news)}")

            for n in news:
                uid = make_uid(n)
                if uid in state:
                    counters["dup"] += 1
                    continue

                title_en = (n.get("title") or "").strip()
                desc_en = (n.get("description") or "").strip()

                if any(b in title_en.lower() for b in BLOCK_KEYWORDS):
                    counters["blocked_legal"] += 1
                    state[uid] = time.time()
                    continue

                title_ar = safe_translate(title_en)

                if is_buy_question(title_en, title_ar):
                    counters["buy_question"] += 1
                    state[uid] = time.time()
                    continue

                if is_weak(title_en, title_ar):
                    counters["weak"] += 1
                    state[uid] = time.time()
                    continue

                sc = score_news(title_en, desc_en)
                if sc < SCORE_THRESHOLD:
                    counters["score_low"] += 1
                    state[uid] = time.time()
                    continue

                tickers = (n.get("tickers") or [])[:MAX_TICKERS_PER_NEWS]
                if not tickers:
                    counters["no_tickers"] += 1
                    state[uid] = time.time()
                    continue

                chosen, chosen_price = None, None
                for sym in tickers:
                    sym = str(sym).upper().strip()
                    if not re.match(r"^[A-Z.\-]{1,10}$", sym):
                        continue
                    p = get_price(sym)
                    if p is None:
                        continue
                    if PRICE_MIN <= p <= PRICE_MAX:
                        chosen, chosen_price = sym, p
                        break

                if not chosen:
                    counters["price_out_or_none"] += 1
                    state[uid] = time.time()
                    continue

                msg = f"🚨 <b>{chosen}</b> | ${chosen_price:.2f}\n📰 {title_ar}{FOOTER}"
                Bot(token=TOKEN).send_message(
                    chat_id=CHANNEL,
                    text=msg,
                    parse_mode="HTML",
                    disable_web_page_preview=True
                )
                counters["sent"] += 1
                state[uid] = time.time()
                save_state()

                if DEBUG:
                    print(f"✅ SENT {chosen} ${chosen_price:.2f} | score={sc} | {title_en[:120]}")

                time.sleep(60)  # لا يرسل سبام لو جاء أكثر من خبر

            if DEBUG:
                print("📊 Summary:", counters)
                print("-" * 60)

        except Exception as e:
            print("❌ ERROR:", repr(e))
            traceback.print_exc()

        time.sleep(INTERVAL)

# ================= FLASK SERVER (keeps Web Service alive) =================
app = Flask(__name__)

@app.get("/")
def home():
    return "OK - USMarketNow bot is running"

@app.get("/health")
def health():
    return {"status": "ok", "ts": time.time()}

if __name__ == "__main__":
    # شغّل اللوب بالخلفية
    t = threading.Thread(target=bot_loop, daemon=True)
    t.start()

    # افتح بورت Render
    port = int(os.getenv("PORT", "10000"))
    print(f"🌐 Starting web server on 0.0.0.0:{port}")
    app.run(host="0.0.0.0", port=port)
