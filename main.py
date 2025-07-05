import asyncio
import feedparser
from telegram import Bot
from datetime import datetime, timedelta
import os
from googletrans import Translator
import re

print("✅ Bot is starting...")

TOKEN = "8101036051:AAEMbhWIYv22FOMV6pXcAOosEWxsy9v3jfY"
CHANNEL = "@USMarketnow"
bot = Bot(token=TOKEN)
translator = Translator()

RSS_FEEDS = [
    "https://finance.yahoo.com/news/rssindex",
    "https://www.cnbc.com/id/100003114/device/rss/rss.html",
    "https://sa.investing.com/rss/news_301.rss"
]

KEYWORDS = [
    "الفائدة", "باول", "الذهب", "التضخم", "النفط", "الركود",
    "الضرائب", "البيت الأبيض", "ترامب", "بايدن", "أوبك",
    "الفيدرالي", "قانون", "السوق الأمريكي", "أرباح", "إيران",
    "الأسواق", "الهبوط", "ارتفاع", "مؤشر", "SPX", "داو", "S&P", "NASDAQ"
]

SENT_FILE = "sent_titles.txt"

def load_sent_titles():
    return set(open(SENT_FILE, encoding="utf-8").read().splitlines()) if os.path.exists(SENT_FILE) else set()

def save_sent_title(title):
    with open(SENT_FILE, "a", encoding="utf-8") as f:
        f.write(title.strip() + "\n")

def clean(text):
    return re.sub(r'[*_`]', '', text)

def is_recent(entry):
    if not hasattr(entry, 'published_parsed'):
        return True
    pub_time = datetime(*entry.published_parsed[:6])
    return pub_time > datetime.utcnow() - timedelta(hours=3)

def is_important(text):
    return any(word.lower() in text.lower() for word in KEYWORDS)

def is_arabic_source(url):
    return "investing.com" in url

async def send_news():
    sent_titles = load_sent_titles()
    print("🔍 Checking feeds...")
    for url in RSS_FEEDS:
        try:
            feed = feedparser.parse(url)
            arabic = is_arabic_source(url)

            for entry in feed.entries[:10]:
                title = entry.title.strip()
                if title in sent_titles or not is_recent(entry):
                    continue

                full_text = title + " " + (entry.get("description", "") or "")
                if not is_important(full_text):
                    continue

                if not arabic:
                    try:
                        full_text = translator.translate(full_text, dest='ar').text
                    except Exception as e:
                        print("⚠️ Translation failed:", e)

                full_text = clean(full_text)
                if len(full_text) > 350:
                    full_text = full_text[:350] + "..."

                # 🟢 تنسيق الرسالة مع رابط القناة في النهاية
                msg = f"""📢 *خبر عاجل مؤثر:*\n
📰 *{title}*\n
{full_text}
📎 [رابط الخبر]({entry.link})

📡 لمتابعة أهم أخبار السوق الأمريكي:
https://t.me/USMarketnow
"""
                await bot.send_message(chat_id=CHANNEL, text=msg, parse_mode="Markdown", disable_web_page_preview=True)
                print("✅ Sent:", title)
                save_sent_title(title)
                await asyncio.sleep(1)

        except Exception as e:
            print("❌ Feed error:", url, e)

async def loop_forever():
    while True:
        try:
            await send_news()
        except Exception as e:
            print("❌ Unexpected error:", e)
        await asyncio.sleep(300)

if __name__ == "__main__":
    asyncio.run(loop_forever())
