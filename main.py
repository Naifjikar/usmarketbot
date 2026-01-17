import os
import re
import asyncio
import hashlib
from datetime import datetime, timezone

import aiohttp
import aiosqlite
from telegram import Bot
from deep_translator import GoogleTranslator

# ================== ENV CONFIG ==================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")  # @USMarketnow أو ID
BENZINGA_KEY = os.getenv("BENZINGA_KEY")

POLL_SEC = int(os.getenv("POLL_SEC", "60"))
MAX_PULL = int(os.getenv("MAX_PULL", "50"))
DB_PATH = os.getenv("DB_PATH", "news_state.db")
DEBUG = os.getenv("DEBUG", "1") == "1"
# ================================================

if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID or not BENZINGA_KEY:
    raise SystemExit("❌ Missing ENV vars")

bot = Bot(token=TELEGRAM_TOKEN)
translator = GoogleTranslator(source="auto", target="ar")

# ========= FILTERING =========
BLOCK_PATTERNS = [
    r"class action", r"shareholder alert", r"law firm", r"investigation",
    r"lawsuit", r"attorney", r"globe newswire", r"prnewswire"
]

IMPORTANT_KEYWORDS = [
    "fed", "fomc", "powell", "interest rate", "cpi", "inflation",
    "jobs", "nonfarm", "gdp", "treasury", "white house",
    "earnings", "guidance", "upgrade", "downgrade",
    "fda", "approval", "clinical", "trial",
    "acquisition", "merger", "buyback", "stock split"
]
# =============================

def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower()).strip()

def is_blocked(title: str, body: str) -> bool:
    txt = normalize(title) + " " + normalize(body)
    return any(re.search(p, txt) for p in BLOCK_PATTERNS)

def score_news(title: str, body: str) -> int:
    txt = normalize(title) + " " + normalize(body)
    score = 0
    for k in IMPORTANT_KEYWORDS:
        if k in txt:
            score += 2
    return score

def make_hash(title: str, body: str) -> str:
    raw = f"{title}|{body}".encode("utf-8", errors="ignore")
    return hashlib.sha256(raw).hexdigest()

# ========== DATABASE ==========
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS sent_news (
                id TEXT PRIMARY KEY,
                sent_at TEXT
            )
        """)
        await db.commit()

async def already_sent(news_id: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT 1 FROM sent_news WHERE id = ?", (news_id,)) as cur:
            return await cur.fetchone() is not None

async def mark_sent(news_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO sent_news VALUES (?, ?)",
            (news_id, datetime.now(timezone.utc).isoformat())
        )
        await db.commit()
# ===============================

async def fetch_benzinga(session):
    url = "https://api.benzinga.com/api/v2/news"
    params = {
        "token": BENZINGA_KEY,
        "pageSize": MAX_PULL
    }
    async with session.get(url, params=params, timeout=20) as r:
        r.raise_for_status()
        return await r.json()

async def send_to_telegram(title_en: str, body_text: str):
    try:
        title_ar = translator.translate(title_en)
    except Exception:
        title_ar = title_en

    message = (
        f"🗞️ {title_ar}\n\n"
        f"{body_text.strip()}\n\n"
        "لمتابعة الاخبار العاجلة | البورصة الامريكة\n"
        "https://t.me/USMarketnow"
    )

    await bot.send_message(
        chat_id=TELEGRAM_CHAT_ID,
        text=message,
        disable_web_page_preview=True
    )

# ========== MAIN LOOP ==========
async def main():
    await init_db()
    async with aiohttp.ClientSession() as session:
        while True:
            try:
                data = await fetch_benzinga(session)
                items = data.get("data") or data.get("news") or []

                if DEBUG:
                    print(f"📥 Pulled {len(items)} news")

                for item in items:
                    title = item.get("title") or ""
                    body = item.get("body") or item.get("content") or ""

                    if not title or not body:
                        continue

                    if is_blocked(title, body):
                        continue

                    if score_news(title, body) < 3:
                        continue

                    news_id = make_hash(title, body)
                    if await already_sent(news_id):
                        continue

                    await send_to_telegram(title, body[:1500])
                    await mark_sent(news_id)

            except Exception as e:
                print("❌ ERROR:", e)

            await asyncio.sleep(POLL_SEC)

if __name__ == "__main__":
    asyncio.run(main())
