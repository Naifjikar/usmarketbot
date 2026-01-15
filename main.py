import os, time, json, re, threading, traceback
import requests
from flask import Flask

# ================== CONFIG (يفضل ENV على Render) ==================
TOKEN = os.getenv("TOKEN", "PUT_TELEGRAM_TOKEN_HERE")
CHANNEL = os.getenv("CHANNEL", "@USMarketnow")
POLYGON_KEY = os.getenv("POLYGON_KEY", "PUT_POLYGON_KEY_HERE")

POLL_SECONDS = int(os.getenv("POLL_SECONDS", "60"))  # تحديث كل دقيقة
MAX_NEWS = int(os.getenv("MAX_NEWS", "80"))
MAX_TICKERS_PER_NEWS = int(os.getenv("MAX_TICKERS_PER_NEWS", "8"))

PRICE_MIN = float(os.getenv("PRICE_MIN", "0.01"))
PRICE_MAX = float(os.getenv("PRICE_MAX", "10.0"))

SCORE_THRESHOLD = int(os.getenv("SCORE_THRESHOLD", "3"))  # شرط القوة
POST_COOLDOWN_SEC = int(os.getenv("POST_COOLDOWN_SEC", "90"))  # بين الرسائل لتقليل السبام

STATE_FILE = os.getenv("STATE_FILE", "news_state.json")

FOOTER = (
    "\n\nتابعنا لمتابعة الاخبار اللحظية\n"
    "⚠️ البورصة الامريكية | عاجل\n"
    "https://t.me/USMarketnow"
)

DEBUG = os.getenv("DEBUG", "1") == "1"

# ================== FILTERS ==================
# منع قضايا/مكاتب محاماة (ضعيفة ومزعجة)
BLOCK_KEYWORDS = [
    "class action", "lawsuit", "law firm", "investors are encouraged",
    "deadline", "litigation", "rosen", "pomerantz", "glancy",
    "levi & korsinsky", "korsinsky", "investigation",
    "shareholder alert", "securities fraud"
]

# منع ترشيحات/تحليلات/أسئلة شراء
WEAK_KEYWORDS = [
    "stocks to watch", "watchlist", "top ", "best ", "favorite", "picks",
    "should you buy", "should i buy", "is it time to buy", "buy now",
    "price target", "analyst", "rating", "upgrade", "downgrade",
    "opinion", "analysis", "preview", "why you should", "undervalued", "overvalued",
    "buy the dip"
]
AR_WEAK = [
    "أفضل", "افضل", "للشراء", "شراء الآن", "ترشيحات", "توصيات", "قائمة",
    "هل اشتري", "هل نشتري", "هل يجب", "هل عليك"
]

# كلمات تعطي “خبر قوي”
STRONG_KEYWORDS = {
    # FDA/علاج
    "fda": 3, "approval": 3, "cleared": 2,
    "phase 1": 3, "phase 2": 3, "phase 3": 4,
    "clinical trial": 4, "trial results": 4,
    "breakthrough": 3, "patent": 2,
    # استحواذ/صفقات
    "acquisition": 4, "acquires": 4, "to acquire": 4,
    "merger": 4, "definitive agreement": 4,
    "contract award": 4, "awarded": 3, "contract": 3, "partnership": 3,
    # أرباح
    "earnings": 3, "eps": 4, "revenue": 3, "guidance": 4,
    "raises guidance": 5, "cuts guidance": 4, "beats": 4, "misses": 4,
    # تقني/منتج
    "launch": 2, "launches": 2, "new product": 3, "platform": 2,
    "cybersecurity": 2, "artificial intelligence": 2, " ai ": 2,
    # تقسيم
    "stock split": 4, "reverse split": 4
}

# ================== HELPERS ==================
session = requests.Session()

def log(*args):
    if DEBUG:
        print(*args, flush=True)

def tg_send(text: str):
    # إرسال بدون مكتبة تيليجرام (الأكثر استقرارًا)
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {
        "chat_id": CHANNEL,
        "text": text,
        "disable_web_page_preview": True
    }
    r = session.post(url, json=payload, timeout=25)
    r.raise_for_status()

def pg(path, params=None):
    params = params or {}
    params["apiKey"] = POLYGON_KEY
    r = session.get("https://api.polygon.io" + path, params=params, timeout=25)
    r.raise_for_status()
    return r.json()

def make_uid(n: dict) -> str:
    nid = str(n.get("id") or "").strip()
    if nid:
        return "id:" + nid
    title = (n.get("title") or "").strip().lower()
    pub = (n.get("published_utc") or "").strip()
    return f"tp:{title}|{pub}"

def score_news(title: str, desc: str = "") -> int:
    text = f"{(title or '').lower()} {(desc or '').lower()}"
    if any(w in text for w in WEAK_KEYWORDS):
        return 0
    s = 0
    for k, pts in STRONG_KEYWORDS.items():
        if k in text:
            s += pts
    return s

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

def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_state(state):
    cutoff = time.time() - 30 * 24 * 3600
    compact = {k: v for k, v in state.items() if v >= cutoff}
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(compact, f, ensure_ascii=False, indent=2)

# ================== BOT LOOP ==================
def bot_loop():
    state = load_state()
    while True:
        try:
            log("✅ Tick:", time.strftime("%Y-%m-%d %H:%M:%S"))

            res = pg("/v2/reference/news", {
                "limit": MAX_NEWS,
                "order": "desc",
                "sort": "published_utc"
            })
            news = res.get("results", []) or []
            log(f"📰 fetched={len(news)}")

            sent_this_loop = 0

            for n in news:
                uid = make_uid(n)
                if uid in state:
                    continue

                title_en = (n.get("title") or "").strip()
                desc_en = (n.get("description") or "").strip()
                title_low = title_en.lower()

                # منع القضايا/المحامين
                if any(b in title_low for b in BLOCK_KEYWORDS):
                    state[uid] = time.time()
                    continue

                # منع الضعيف/ترشيحات
                if any(w in title_low for w in WEAK_KEYWORDS):
                    state[uid] = time.time()
                    continue

                # منع كلمات عربية ضعيفة (لو وصلتنا مترجمة من المصدر)
                if any(w in title_en for w in AR_WEAK):
                    state[uid] = time.time()
                    continue

                sc = score_news(title_en, desc_en)
                if sc < SCORE_THRESHOLD:
                    state[uid] = time.time()
                    continue

                tickers = (n.get("tickers") or [])[:MAX_TICKERS_PER_NEWS]
                if not tickers:
                    state[uid] = time.time()
                    continue

                # اختيار أول تيكر سعره ضمن 0.01–10
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
                    state[uid] = time.time()
                    continue

                # بدون رابط نهائيًا (مثل طلبك)
                msg = f"🚨 {chosen} | ${chosen_price:.2f}\n{title_en}{FOOTER}"
                tg_send(msg)

                log(f"✅ SENT: {chosen} ${chosen_price:.2f} | score={sc}")
                state[uid] = time.time()
                save_state(state)

                sent_this_loop += 1
                time.sleep(POST_COOLDOWN_SEC)

            if sent_this_loop == 0:
                log("ℹ️ No posts this loop (filters may be strict).")

        except Exception as e:
            log("❌ ERROR:", repr(e))
            traceback.print_exc()

        time.sleep(POLL_SECONDS)

# ================== FLASK (يبقي Web Service حي) ==================
app = Flask(__name__)

@app.get("/")
def home():
    return "OK - USMarketNow news bot running"

@app.get("/health")
def health():
    return {"status": "ok", "ts": time.time()}

if __name__ == "__main__":
    threading.Thread(target=bot_loop, daemon=True).start()
    port = int(os.getenv("PORT", "10000"))
    log(f"🌐 Flask on 0.0.0.0:{port}")
    app.run(host="0.0.0.0", port=port)
