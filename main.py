import os, time, json, re, threading, traceback
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests
from flask import Flask
from telegram import Bot
from deep_translator import GoogleTranslator

# ===================== CONFIG =====================
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHANNEL = os.getenv("TELEGRAM_CHANNEL", "@USMarketnow").strip()

BENZINGA_KEY = os.getenv("BENZINGA_API_KEY", "").strip()

POLL_SEC = int(os.getenv("POLL_SEC", "60"))  # كل دقيقة
STATE_FILE = os.getenv("STATE_FILE", "news_state.json")
TZ = ZoneInfo("Asia/Riyadh")

PRICE_MIN = float(os.getenv("PRICE_MIN", "0.0"))  # مبدئي (Benzinga News ما يعطي سعر دائمًا)
PRICE_MAX = float(os.getenv("PRICE_MAX", "10.0"))

MIN_SCORE = int(os.getenv("MIN_SCORE", "3"))  # الشرط اللي طلبته

FOOTER = (
    "تابعنا لمتابعة الاخبار اللحظية\n"
    "البورصة الامريكية | عاجل ⚠️\n"
    "https://t.me/USMarketnow"
)

# ================================================

app = Flask(__name__)

if not TOKEN or not BENZINGA_KEY:
    raise SystemExit("❌ Missing env vars: TELEGRAM_BOT_TOKEN and/or BENZINGA_API_KEY")

bot = Bot(token=TOKEN)
translator = GoogleTranslator(source="en", target="ar")

# ----------------- Filtering -----------------

# كلمات/مصادر مزعجة (دعاوى/مكاتب محاماة/تحقيقات)
BORING_PATTERNS = [
    r"\bclass action\b", r"\blawsuit\b", r"\binvestigation\b", r"\bdeadline\b",
    r"\brosen\b", r"\bglancy\b", r"\blevi\b", r"\bportnoy\b", r"\bpomerantz\b",
    r"\bsecurities litigation\b", r"\bfirst filing firm\b", r"\bshareholder\b"
]

# كلمات قوية ترفع السكور
STRONG_KEYWORDS = {
    # استحواذ/اندماج
    "acquisition": 3, "acquire": 3, "merger": 3, "m&a": 3, "takeover": 3,
    # أرباح/توجيهات
    "earnings": 3, "eps": 2, "revenue": 2, "guidance": 3, "raises guidance": 3, "lowers guidance": 3,
    "beats": 2, "misses": 2, "profit": 1,
    # FDA/تجارب/علاج
    "fda": 3, "phase": 2, "trial": 2, "approval": 3, "clinical": 2, "drug": 2,
    "breakthrough": 3, "cancer": 2, "treatment": 2, "cure": 3,
    # عقود/صفقات
    "contract": 3, "partnership": 2, "strategic partnership": 3, "deal": 2, "order": 2,
    # تقسيم/إعادة شراء
    "stock split": 3, "reverse split": 3, "buyback": 2, "repurchase": 2,
    # تمويل/طرح
    "offering": 2, "priced": 2, "private placement": 2, "financing": 2,
    # تقنية/إطلاق
    "launch": 2, "unveils": 2, "announces": 1, "ai": 1, "artificial intelligence": 1,
}

def normalize_text(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip()).lower()

def is_boring(text: str) -> bool:
    t = normalize_text(text)
    return any(re.search(p, t) for p in BORING_PATTERNS)

def score_news(title: str, body: str, categories=None) -> int:
    t = normalize_text(title)
    b = normalize_text(body)
    c = " ".join([normalize_text(x) for x in (categories or [])])

    if is_boring(t + " " + b + " " + c):
        return -999

    score = 0
    blob = f"{t} {b} {c}"

    for k, w in STRONG_KEYWORDS.items():
        if k in blob:
            score += w

    # تعزيز إذا الخبر فئة "Earnings" أو network قوي
    if "earnings" in c:
        score += 2
    if "m&a" in c or "merger" in c:
        score += 2
    if "fda" in c:
        score += 2

    return score

def safe_translate_en_to_ar(text: str) -> str:
    text = (text or "").strip()
    if not text:
        return ""
    # لو النص عربي أصلاً
    if re.search(r"[\u0600-\u06FF]", text):
        return text
    try:
        return translator.translate(text)
    except Exception:
        return text  # fallback

# ----------------- State (dedup) -----------------

def load_state():
    if not os.path.exists(STATE_FILE):
        return {"seen_ids": [], "updated_since": None}
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"seen_ids": [], "updated_since": None}

def save_state(state):
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

STATE = load_state()
SEEN = set(STATE.get("seen_ids", []))
UPDATED_SINCE = STATE.get("updated_since")  # ISO string

# ----------------- Benzinga News Fetch -----------------

BENZINGA_NEWS_URL = "https://api.benzinga.com/api/v2/news"

def fetch_benzinga_news(updated_since: str | None):
    """
    Benzinga Newsfeed v2:
    GET https://api.benzinga.com/api/v2/news?token=KEY&updatedSince=...
    """
    params = {
        "token": BENZINGA_KEY,
        "displayOutput": "full",
        "pageSize": 50,
        "sort": "updated:desc",
    }
    if updated_since:
        params["updatedSince"] = updated_since

    r = requests.get(BENZINGA_NEWS_URL, params=params, timeout=25)
    r.raise_for_status()
    data = r.json()
    # عادة يرجّع قائمة
    if isinstance(data, dict) and "news" in data:
        return data["news"]
    return data if isinstance(data, list) else []

def extract_item_fields(item: dict):
    # بنزينجا يختلف أحيانًا—نحاول نغطي الحقول الشائعة
    news_id = str(item.get("id") or item.get("news_id") or "")
    title = item.get("title") or ""
    created = item.get("created") or item.get("created_at") or item.get("published") or ""
    updated = item.get("updated") or item.get("updated_at") or item.get("updatedUtc") or item.get("updated_utc") or ""
    tickers = item.get("tickers") or item.get("symbols") or []
    if isinstance(tickers, str):
        tickers = [t.strip() for t in tickers.split(",") if t.strip()]
    categories = item.get("channels") or item.get("tags") or item.get("category") or []
    if isinstance(categories, str):
        categories = [c.strip() for c in categories.split(",") if c.strip()]
    body = item.get("body") or item.get("teaser") or item.get("summary") or ""
    return news_id, title, body, tickers, categories, updated or created

def build_message(ticker: str, title_ar: str, source_name="Benzinga"):
    # بدون رابط مثل ما طلبت
    return (
        f"🚨 {ticker}\n"
        f"{title_ar}\n\n"
        f"{FOOTER}"
    )

def should_send_by_price(_ticker: str) -> bool:
    # Benzinga News ما يضمن سعر لحظي في نفس الـ endpoint
    # نتركها True الآن عشان ما يوقف البوت—لو تبي نفلتر بالسعر
    # نضيف Quote endpoint من Benzinga لاحقًا.
    return True

def worker_loop():
    global UPDATED_SINCE

    # عشان أول تشغيل: نرجع آخر 15 دقيقة فقط (حتى ما يغرق القناة)
    if not UPDATED_SINCE:
        dt = datetime.now(tz=ZoneInfo("UTC")) - timedelta(minutes=15)
        UPDATED_SINCE = dt.isoformat().replace("+00:00", "Z")

    while True:
        try:
            items = fetch_benzinga_news(UPDATED_SINCE)

            max_updated = UPDATED_SINCE
            sent_count = 0

            for it in items:
                news_id, title, body, tickers, categories, updated_time = extract_item_fields(it)
                if not news_id:
                    continue
                if news_id in SEEN:
                    continue

                # تحديث cursor
                if updated_time and (not max_updated or str(updated_time) > str(max_updated)):
                    max_updated = updated_time

                # أهم شرط: لازم يكون في ticker
                if not tickers:
                    SEEN.add(news_id)
                    continue

                # قيّم القوة
                s = score_news(title, body, categories)
                if s < MIN_SCORE:
                    SEEN.add(news_id)
                    continue

                # فلتر سعر (مبدئي)
                main_ticker = str(tickers[0]).upper()
                if not should_send_by_price(main_ticker):
                    SEEN.add(news_id)
                    continue

                # ترجمة
                title_ar = safe_translate_en_to_ar(title)

                msg = build_message(main_ticker, title_ar)

                bot.send_message(chat_id=CHANNEL, text=msg, disable_web_page_preview=True)
                sent_count += 1

                SEEN.add(news_id)

                # لا يرسل سبام
                if sent_count >= 10:
                    break

            UPDATED_SINCE = max_updated

            # حفظ حالة منع التكرار
            STATE["seen_ids"] = list(list(SEEN)[-4000:])  # cap
            STATE["updated_since"] = UPDATED_SINCE
            save_state(STATE)

        except Exception as e:
            print("ERROR:", repr(e))
            traceback.print_exc()

        time.sleep(POLL_SEC)

# ----------------- Keep Render alive -----------------

@app.get("/")
def home():
    return "OK - USMarketnow Benzinga Bot is running."

def start_background():
    t = threading.Thread(target=worker_loop, daemon=True)
    t.start()

if __name__ == "__main__":
    start_background()
    port = int(os.getenv("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
