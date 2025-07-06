import asyncio
import feedparser
from telegram import Bot
from datetime import datetime, timedelta
from googletrans import Translator
import os
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
    "الفائدة", "الفيدرالي", "باول", "التضخم", "الذهب", "النفط", "الركود",
    "البيت الأبيض", "ترامب", "بايدن", "أوبك", "البطالة", "سوق العمل",
    "الانتخابات", "أرباح", "قانون", "إيران", "هجوم", "ضربة", "قصف"
]

SENT_FILE = "sent_titles.txt"

def load_sent_titles():
    if os.path.exists(SENT_FILE):
        with open(SENT_FILE, "r", encoding="utf-8") as f:
            return set(f.read().splitlines())
    return set()

def save_sent_title(title):
    with open(SENT_FILE, "a", encoding="utf-8") as f:
        f.write(title.strip() + "\n")

def clean(text):
    return re.sub(r'[*_`]', '', text)

def is_recent(entry):
    if hasattr(entry, 'published_parsed'):
        pub_time = datetime(*entry.published_parsed[:6])
        return pub_time > datetime.utcnow() - timedelta(hours=3)
    return True

def is_important(text):
    return any(word.lower() in text.lower() for word in KEYWORDS)

def is_arabic_source(url):
    return "investing.com" in url

def generate_title(text):
    lowered = text.lower()
    if any(k in lowered for k in ["باول", "الفائدة", "الفيدرالي", "رفع", "خفض"]):
        return "📢 خبر عاجل عن الفيدرالي:"
    elif any(k in lowered for k in ["التضخم", "cpi", "الأسعار"]):
        return "📊 خبر عن التضخم:"
    elif any(k in lowered for k in ["أرباح", "تقرير", "نتائج"]):
        return "💰 تقرير أرباح:"
    elif any(k in lowered for k in ["البيت الأبيض", "بايدن", "ترامب"]):
        return "🏛️ خبر من البيت الأبيض:"
    elif any(k in lowered for k in ["إيران", "ضربة", "قصف", "هجوم"]):
        return "🚨 خبر أمني عاجل:"
    else:
        return "📍 خبر مؤثر:"

async def send_news():
    sent_titles = load_sent_titles()
    print("🔍 Checking feeds...")
    for url in RSS_FEEDS:
        try:
            feed = feedparser.parse(url)
            arabic_source = is_arabic_source(url)

            for entry in feed.entries[:10]:
                title = entry.title.strip()
                description = entry.get("description", "").strip()
                full_text = f"{title} {description}"

                if title in sent_titles or not is_recent(entry):
                    continue

                if not is_important(full_text):
                    continue

                # الترجمة إذا ما كان المصدر عربي
                if not arabic_source:
                    try:
                        full_text = translator.translate(full_text, dest='ar').text
                    except Exception as e:
                        print("⚠️ Translation failed:", e)

                full_text = clean(full_text)
                if len(full_text) > 300:
                    full_text = full_text[:300] + "..."

                header = generate_title(full_text)
                msg = f"{header}\n\n{full_text}\n📎 [رابط الخبر]({entry.link})\n\n📡 لمتابعة أهم أخبار السوق الأمريكي:\nhttps://t.me/USMarketnow"

                await bot.send_message(chat_id=CHANNEL, text=msg, parse_mode="Markdown", disable_web_page_preview=True)
                print("✅ Sent:", title)
                save_sent_title(title)
                await asyncio.sleep(1)

        except Exception as e:
            print("❌ Error processing feed:", url, e)

async def loop_forever():
    while True:
        await send_news()
        await asyncio.sleep(300)

if __name__ == "__main__":
    asyncio.run(loop_forever())
