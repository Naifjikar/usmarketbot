import asyncio, requests, time, json, os, re
from telegram import Bot
from deep_translator import GoogleTranslator

# ====== CONFIG ======
TOKEN = "8101036051:AAEMbhWIYv22FOMV6pXcAOosEWxsy9v3jfY"
CHANNEL = "@USMarketnow"
POLYGON_KEY = "ht3apHm7nJA2VhvBynMHEcpRI11VSRbq"

PRICE_MIN, PRICE_MAX = 0.01, 10.0
INTERVAL = 180
STATE_FILE = "news_state.json"
MAX_NEWS = 40
MAX_TICKERS_PER_NEWS = 6

FOOTER = (
    "\n\nتابعنا لمتابعة الاخبار اللحظية\n"
    "البورصة الامريكية | عاجل ⚠️\n"
    "https://t.me/USMarketnow"
)

bot = Bot(token=TOKEN)
tr = GoogleTranslator(source="auto", target="ar")

def translate(text: str) -> str:
    text = (text or "").strip()
    if not text:
        return ""
    try:
        return tr.translate(text)
    except Exception:
        return text

# ====== STATE (DEDUP) ======
state = json.load(open(STATE_FILE, "r", encoding="utf-8")) if os.path.exists(STATE_FILE) else {}

def save_state():
    cutoff = time.time() - 30 * 24 * 3600
    compact = {k: v for k, v in state.items() if v >= cutoff}
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(compact, f, ensure_ascii=False, indent=2)

def seen(uid: str) -> bool:
    return uid in state

def mark(uid: str):
    state[uid] = time.time()
    save_state()

# ====== POLYGON ======
def pg(path, params=None):
    params = params or {}
    params["apiKey"] = POLYGON_KEY
    r = requests.get("https://api.polygon.io" + path, params=params, timeout=20)
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

def make_uid(n: dict) -> str:
    # أقوى منع تكرار: id لو موجود
    nid = str(n.get("id") or "").strip()
    if nid:
        return f"id:{nid}"
    # fallback: title + time
    title = (n.get("title") or "").strip().lower()
    pub = (n.get("published_utc") or "").strip()
    return f"tp:{title}|{pub}"

# ====== LOOP ======
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
                if seen(uid):
                    continue  # ✅ منع تكرار الخبر بالكامل (حتى لو فيه أكثر من سهم)

                tickers = n.get("tickers", []) or []
                # نختار أول سهم ضمن السعر (عشان ما نكرر نفس الخبر بعدة أسهم)
                chosen = None
                chosen_price = None
                for sym in tickers[:MAX_TICKERS_PER_NEWS]:
                    sym = str(sym).upper().strip()
                    if not re.match(r"^[A-Z.\-]{1,10}$", sym):
                        continue
                    p = get_price(sym)
                    if p and (PRICE_MIN <= p <= PRICE_MAX):
                        chosen = sym
                        chosen_price = p
                        break

                if not chosen:
                    continue

                title_ar = translate(n.get("title", ""))
                msg = f"🚨 <b>{chosen}</b> | ${chosen_price:.2f}\n📰 {title_ar}{FOOTER}"

                await bot.send_message(
                    chat_id=CHANNEL,
                    text=msg,
                    parse_mode="HTML",
                    disable_web_page_preview=True
                )

                mark(uid)  # ✅ نسجل الخبر بعد الإرسال
                await asyncio.sleep(1)

        except Exception as e:
            print("ERR:", e)

        await asyncio.sleep(INTERVAL)

asyncio.run(run())
