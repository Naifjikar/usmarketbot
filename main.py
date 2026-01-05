import asyncio, requests, time, json, os, re, traceback
from telegram import Bot
from deep_translator import GoogleTranslator

# ================= CONFIG =================
# ملاحظة: الأفضل تحطها كـ ENV على Render
TOKEN = os.getenv("TOKEN", "8101036051:AAEMbhWIYv22FOMV6pXcAOosEWxsy9v3jfY")
CHANNEL = os.getenv("CHANNEL", "@USMarketnow")
POLYGON_KEY = os.getenv("POLYGON_KEY", "ht3apHm7nJA2VhvBynMHEcpRI11VSRbq")

PRICE_MIN, PRICE_MAX = 0.01, 10.0
INTERVAL = 60
MAX_NEWS = 120
MAX_TICKERS_PER_NEWS = 12
STATE_FILE = "news_state.json"

SCORE_THRESHOLD = 3  # حسب طلبك

FOOTER = (
    "\n\nتابعنا لمتابعة الاخبار اللحظية\n"
    "⚠️ البورصة الامريكية | عاجل\n"
    "https://t.me/USMarketnow"
)

DEBUG = True  # ✅ يخلي اللوق يوضح كل شيء

# ================= BLOCK (محامين/قضايا) =================
BLOCK_KEYWORDS = [
    "class action", "lawsuit", "law firm", "investors are encouraged",
    "deadline", "litigation", "rosen", "pomerantz", "glancy",
    "levi & korsinsky", "korsinsky", "investigation",
    "shareholder alert", "securities fraud"
]

# ================= WEAK (ترشيحات/تحليل/قوائم/رأي) =================
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

# ✅ منع أسلوب "هل تشتري؟ / should you buy?"
QUESTION_BUY_PATTERNS_EN = [
    "should you buy", "should i buy", "is it time to buy", "is it a good time to buy"
]
QUESTION_BUY_PATTERNS_AR = [
    "هل يجب عليك شراء", "هل عليك شراء", "هل يجب شراء", "هل اشتري", "هل نشتري", "هل يجب"
]

# ================= STRONG (أخبار قوية) =================
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

    # أحداث أخرى قوية
    "buyback": 3, "share repurchase": 3,
    "stock split": 4, "reverse split": 4
}

# ================= INIT =================
bot = Bot(token=TOKEN)
translator = GoogleTranslator(source="auto", target="ar")
session = requests.Session()

state = json.load(open(STATE_FILE, "r", encoding="utf-8")) if os.path.exists(STATE_FILE) else {}

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
    a = (title_ar or "")
    if any(w in a for w in AR_WEAK):
        return True
    return False

def is_buy_question(title_en: str, title_ar: str) -> bool:
    t = (title_en or "").lower()
    a = (title_ar or "")
    if "?" in t or "؟" in a:
        # مو كل سؤال ممنوع، لكن أسئلة الشراء/الترشيح ممنوعة
        if any(p in t for p in QUESTION_BUY_PATTERNS_EN):
            return True
        if any(p in a for p in QUESTION_BUY_PATTERNS_AR):
            return True
    # حتى بدون علامة سؤال
    if any(p in t for p in QUESTION_BUY_PATTERNS_EN):
        return True
    if any(p in a for p in QUESTION_BUY_PATTERNS_AR):
        return True
    return False

def score_news(title: str, desc: str = "") -> int:
    t = (title or "").lower()
    d = (desc or "").lower()
    text = f"{t} {d}"
    if any(w in text for w in WEAK_KEYWORDS):
        return 0
    s = 0
    for k, pts in STRONG_KEYWORDS.items():
        if k in text:
            s += pts
    return s

# ================= LOOP =================
async def run():
    while True:
        tick_ts = time.strftime("%Y-%m-%d %H:%M:%S")
        if DEBUG:
            print(f"✅ Tick alive: {tick_ts} | checking Polygon news...")

        counters = {
            "fetched": 0,
            "sent": 0,
            "dup": 0,
            "blocked_legal": 0,
            "weak": 0,
            "buy_question": 0,
            "score_low": 0,
            "no_tickers": 0,
            "no_price": 0,
            "price_out": 0,
            "no_valid_ticker": 0,
        }
        samples = []  # (reason, title)

        try:
            news = pg("/v2/reference/news", {
                "limit": MAX_NEWS,
                "order": "desc",
                "sort": "published_utc"
            }).get("results", []) or []

            counters["fetched"] = len(news)
            if DEBUG:
                print(f"📰 fetched news: {len(news)}")

            for n in news:
                uid = make_uid(n)
                if uid in state:
                    counters["dup"] += 1
                    continue

                title_en = (n.get("title") or "").strip()
                desc_en = (n.get("description") or "").strip()
                tickers = (n.get("tickers") or [])[:MAX_TICKERS_PER_NEWS]

                # 1) منع المحامين
                if any(b in title_en.lower() for b in BLOCK_KEYWORDS):
                    counters["blocked_legal"] += 1
                    samples.append(("blocked_legal", title_en))
                    state[uid] = time.time()
                    continue

                # 2) ترجمة
                title_ar = safe_translate(title_en)

                # 3) منع أسئلة الشراء/الترشيح
                if is_buy_question(title_en, title_ar):
                    counters["buy_question"] += 1
                    samples.append(("buy_question", title_en))
                    state[uid] = time.time()
                    continue

                # 4) منع قوائم/تحليل/ترشيحات
                if is_weak(title_en, title_ar):
                    counters["weak"] += 1
                    samples.append(("weak", title_en))
                    state[uid] = time.time()
                    continue

                # 5) شرط القوة بالسكور
                sc = score_news(title_en, desc_en)
                if sc < SCORE_THRESHOLD:
                    counters["score_low"] += 1
                    samples.append((f"score_low({sc})", title_en))
                    state[uid] = time.time()
                    continue

                # 6) لازم يكون فيه تيكر
                if not tickers:
                    counters["no_tickers"] += 1
                    samples.append(("no_tickers", title_en))
                    state[uid] = time.time()
                    continue

                # 7) اختيار سهم ضمن السعر
                chosen, chosen_price = None, None
                valid_any = False

                for sym in tickers:
                    sym = str(sym).upper().strip()
                    if not re.match(r"^[A-Z.\-]{1,10}$", sym):
                        continue
                    valid_any = True
                    p = get_price(sym)
                    if p is None:
                        continue
                    if not (PRICE_MIN <= p <= PRICE_MAX):
                        continue
                    chosen, chosen_price = sym, p
                    break

                if not valid_any:
                    counters["no_valid_ticker"] += 1
                    samples.append(("no_valid_ticker", title_en))
                    state[uid] = time.time()
                    continue

                if chosen is None:
                    # نحدد هل المشكلة no_price أو price_out
                    # (تقريبًا: إذا كل الأسعار None => no_price, غير كذا price_out)
                    any_price = False
                    any_out = False
                    for sym in tickers:
                        sym = str(sym).upper().strip()
                        if not re.match(r"^[A-Z.\-]{1,10}$", sym):
                            continue
                        p = get_price(sym)
                        if p is None:
                            continue
                        any_price = True
                        if not (PRICE_MIN <= p <= PRICE_MAX):
                            any_out = True
                    if not any_price:
                        counters["no_price"] += 1
                        samples.append(("no_price", title_en))
                    elif any_out:
                        counters["price_out"] += 1
                        samples.append(("price_out", title_en))
                    else:
                        counters["no_price"] += 1
                        samples.append(("no_price", title_en))

                    state[uid] = time.time()
                    continue

                # ✅ إرسال
                msg = f"🚨 <b>{chosen}</b> | ${chosen_price:.2f}\n📰 {title_ar}{FOOTER}"
                await bot.send_message(
                    chat_id=CHANNEL,
                    text=msg,
                    parse_mode="HTML",
                    disable_web_page_preview=True
                )
                counters["sent"] += 1
                state[uid] = time.time()
                save_state()

                if DEBUG:
                    print(f"✅ SENT: {chosen} ${chosen_price:.2f} | score={sc} | {title_en[:120]}")

                await asyncio.sleep(90)  # توزيع بسيط بين الرسائل

        except Exception as e:
            print("❌ ERROR:", repr(e))
            traceback.print_exc()

        # ملخص كل دورة
        if DEBUG:
            print("—" * 60)
            print("📊 Loop Summary:", counters)
            # اعرض آخر 2 مرفوضة من كل سبب (تقريبًا)
            if samples:
                print("🧪 Sample rejects (latest 5):")
                for reason, ttl in samples[-5:]:
                    print(f"   - {reason}: {ttl[:140]}")
            print("—" * 60)

        await asyncio.sleep(INTERVAL)

asyncio.run(run())
