import asyncio, requests, time, json, os, re
from telegram import Bot
from deep_translator import GoogleTranslator

# ====== CONFIG ======
TOKEN = "8101036051:AAEMbhWIYv22FOMV6pXcAOosEWxsy9v3jfY"
CHANNEL = "@USMarketnow"
POLYGON_KEY = "ht3apHm7nJA2VhvBynMHEcpRI11VSRbq"

PRICE_MIN, PRICE_MAX = 0.01, 10.0

# يشتغل طوال الوقت: كل كم ثانية يفحص أخبار جديدة
INTERVAL = 60  # دقيقة (غيّرها لو تبي أسرع/أبطأ)

MAX_NEWS = 60
MAX_TICKERS_PER_NEWS = 8
STATE_FILE = "news_state.json"

FOOTER = (
    "\n\nتابعنا لمتابعة الاخبار اللحظية\n"
    "البورصة الامريكية | عاجل ⚠️\n"
    "https://t.me/USMarketnow"
)

# فلتر لمنع أخبار الدعاوى والمحامين (المزعجة)
BLOCK_KEYWORDS = [
    "class action", "lawsuit", "law firm", "investors are encouraged", "deadline",
    "securities litigation", "securities class action", "litigation",
    "rosen", "pomerantz", "glancy", "levi & korsinsky", "korsinsky",
    "the rosen law firm", "bronstein", "schall law", "rigrodsky", "kahn swick",
    "kirby mcinerney", "lowey", "gross law", "portnoy", "faruqi", "abramson",
    "securities fraud", "shareholder alert", "investigation", "alert"
]

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
    # احتفظ بآخر 30 يوم فقط
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

# ====== POLYGON ======
def pg(path, params=None):
    params = params or {}
    params["apiKey"] = POLYGON_KEY
    r = requests.get("https://api.polygon.io" + path, params=params, timeout=25)
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

def is_blocked_title(title: str) -> bool:
    t = (title or "").lower()
    return any(k in t for k in BLOCK_KEYWORDS)

# ====== LOOP ======
async def run():
    while True:
        try:
            data = pg("/v2/reference/news", {
                "limit": MAX_NEWS,
                "order": "desc",
                "sort": "published_utc"
            })
            news = data.get("results", []) or []

            for n in news:
                uid = make_uid(n)
                if uid in state:
                    continue  # ✅ منع تكرار الخبر بالكامل

                title_en = n.get("title") or ""
                if is_blocked_title(title_en):
                    state[uid] = time.time()  # نعلّم عليه حتى ما يرجع يطلع كل دقيقة
                    continue

                tickers = n.get("tickers", []) or []
                chosen, chosen_price = None, None

                # اختر أول سهم ضمن السعر المطلوب
                for sym in tickers[:MAX_TICKERS_PER_NEWS]:
                    sym = str(sym).upper().strip()
                    if not re.match(r"^[A-Z.\-]{1,10}$", sym):
                        continue
                    p = get_price(sym)
                    if p and (PRICE_MIN <= p <= PRICE_MAX):
                        chosen, chosen_price = sym, p
                        break

                if not chosen:
                    # علّم الخبر حتى ما يعيد تدويره
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
                await asyncio.sleep(1)

        except Exception as e:
            print("ERR:", e)

        await asyncio.sleep(INTERVAL)

asyncio.run(run())
