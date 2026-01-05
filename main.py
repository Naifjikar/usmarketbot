import asyncio, requests, time, json, os, re
from telegram import Bot
from deep_translator import GoogleTranslator

# ================= CONFIG =================
TOKEN = "8101036051:AAEMbhWIYv22FOMV6pXcAOosEWxsy9v3jfY"
CHANNEL = "@USMarketnow"
POLYGON_KEY = "ht3apHm7nJA2VhvBynMHEcpRI11VSRbq"

PRICE_MIN, PRICE_MAX = 0.01, 10.0
INTERVAL = 60                 # يفحص الأخبار كل دقيقة
MAX_NEWS = 80
MAX_TICKERS_PER_NEWS = 8
STATE_FILE = "news_state.json"

FOOTER = (
    "\n\nتابعنا لمتابعة الاخبار اللحظية\n"
    "⚠️ البورصة الامريكية | عاجل\n"
    "https://t.me/USMarketnow"
)

# ================= BLOCKED (قانوني) =================
BLOCK_KEYWORDS = [
    "class action", "lawsuit", "law firm", "investors are encouraged",
    "deadline", "litigation", "rosen", "pomerantz", "glancy",
    "levi & korsinsky", "korsinsky", "investigation",
    "shareholder alert", "securities fraud"
]

# ================= STRONG / WEAK =================
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
    "deal": 2, "contract": 3, "agreement": 2,
    "partnership": 2, "strategic partnership": 3,

    # أرباح / نتائج
    "earnings": 3, "eps": 4, "revenue": 3,
    "guidance": 4, "raises guidance": 5,
    "beats": 4, "misses": 4,
    "profit": 3, "net income": 3,

    # تقنية / إطلاق
    "launch": 2, "launches": 2,
    "new product": 3, "platform": 2,
    "ai": 2, "artificial intelligence": 2,
    "chip": 2, "cybersecurity": 2,

    # أحداث أخرى
    "buyback": 3, "share repurchase": 3,
    "stock split": 4, "reverse split": 4,
    "dividend": 2
}

WEAK_KEYWORDS = [
    "how", "what is", "explained", "opinion", "analysis",
    "preview", "stocks to watch", "top", "best",
    "why", "could", "might", "price target",
    "rating", "upgrade", "downgrade", "outlook"
]

SCORE_THRESHOLD = 3   # 🔥 الشرط المطلوب

# ================= INIT =================
bot = Bot(token=TOKEN)
translator = GoogleTranslator(source="auto", target="ar")

state = json.load(open(STATE_FILE, "r", encoding="utf-8")) if os.path.exists(STATE_FILE) else {}

def save_state():
    cutoff = time.time() - 30 * 24 * 3600
    compact = {k: v for k, v in state.items() if v >= cutoff}
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(compact, f, ensure_ascii=False, indent=2)

def make_uid(n: dict) -> str:
    if n.get("id"):
        return f"id:{n['id']}"
    return f"{(n.get('title','')).lower()}|{n.get('published_utc','')}"

def translate(text: str) -> str:
    try:
        return translator.translate(text)
    except Exception:
        return text

def news_score(title: str, desc: str = "") -> int:
    t = (title or "").lower()
    d = (desc or "").lower()
    text = f"{t} {d}"

    if any(w in text for w in WEAK_KEYWORDS):
        return 0

    score = 0
    for k, pts in STRONG_KEYWORDS.items():
        if k in text:
            score += pts
    return score

def pg(path, params=None):
    params = params or {}
    params["apiKey"] = POLYGON_KEY
    r = requests.get("https://api.polygon.io" + path, params=params, timeout=25)
    r.raise_for_status()
    return r.json()

_price_cache = {}

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
        if p:
            p = float(p)
            if p > 0:
                _price_cache[sym] = (p, now)
                return p
    except Exception:
        pass
    return None

# ================= LOOP =================
async def run():
    while True:
        try:
            news = pg("/v2/reference/news", {
                "limit": MAX_NEWS,
                "order": "desc",
                "sort": "published_utc"
            }).get("results", [])

            for n in news:
                uid = make_uid(n)
                if uid in state:
                    continue

                title_en = n.get("title", "")
                desc_en = n.get("description", "")

                if any(b in title_en.lower() for b in BLOCK_KEYWORDS):
                    state[uid] = time.time()
                    continue

                score = news_score(title_en, desc_en)
                if score < SCORE_THRESHOLD:
                    state[uid] = time.time()
                    continue

                chosen, chosen_price = None, None
                for sym in (n.get("tickers") or [])[:MAX_TICKERS_PER_NEWS]:
                    if not re.match(r"^[A-Z.\-]{1,10}$", str(sym)):
                        continue
                    p = get_price(sym)
                    if p and PRICE_MIN <= p <= PRICE_MAX:
                        chosen, chosen_price = sym, p
                        break

                if not chosen:
                    state[uid] = time.time()
                    continue

                title_ar = translate(title_en)
                msg = f"🚨 <b>{chosen}</b> | ${chosen_price:.2f}\n📰 {title_ar}{FOOTER}"

                await bot.send_message(
                    chat_id=CHANNEL,
                    text=msg,
                    parse_mode="HTML",
                    disable_web_page_preview=True
                )

                state[uid] = time.time()
                save_state()
                await asyncio.sleep(180)  # توزيع زمني بين الأخبار

        except Exception as e:
            print("ERR:", e)

        await asyncio.sleep(INTERVAL)

asyncio.run(run())
