import asyncio
import feedparser
from telegram import Bot
from datetime import datetime, timedelta
import os
import re
from googletrans import Translator

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
    "باول", "الفائدة", "رفع الفائدة", "خفض الفائدة", "البيت الأبيض", "ترامب", "بايدن",
    "أوبك", "cpi", "التضخم", "تقرير الوظائف", "الفيدرالي", "الركود", "الانكماش",
    "سوق العمل", "الذهب", "الدولار", "البطالة", "الكونغرس", "الرئيس الأمريكي",
    "الانتخابات", "ضربة", "هجوم", "قصف", "إيران", "إسرائيل", "النفط", "أرباح", "الحرب",
    "سباكس", "spx", "s&p500", "الداو", "الداو جونز", "وول ستريت"
]

SENT_FILE = "sent_titles.txt"

def load_sent_titles():
    if not os.path.exists(SENT_FILE):
        return set()
    with open(SENT_FILE, "r", encoding="utf-8") as f:
        return set(line.strip() for line in f)

def save_sent_title(title):
    with open(SENT_FILE, "a", encoding="utf-8") as f:
        f.write(title.strip() + "\n")

def is_recent(entry):
    if not hasattr(entry, 'published_parsed'):
        return True
    pub_time = datetime(*entry.published_parsed[:6])
    return pub_time > datetime.utcnow() - timedelta(hours=3)

def is_important(text):
    return any(word.lower() in text.lower() for word in KEYWORDS)

def clean_text(text):
    return re.sub(r'[*_`]', '', text)

def is_arabic_feed(url):
    return "investing.com" in url

def extract_title(text):
    text = text.lower()
    if "powell" in text or "باول" in text:
        return "🔴 عاجل | جيروم باول يتحدث"
    elif "interest rate" in text or "الفائدة" in text:
        return "📊 عاجل | قرار الفائدة الأمريكية"
    elif "white house" in text or "البيت الأبيض" in text:
        return "🏛️ عاجل | البيت الأبيض"
    elif "trump" in text or "ترامب" in text:
        return "🇺🇸 عاجل | تصريحات ترامب"
    elif "biden" in text or "بايدن" in text:
        return "🟦 عاجل | تصريحات بايدن"
    elif "cpi" in text or "التضخم" in text:
        return "📉 عاجل | بيانات التضخم"
    elif "jobs report" in text or "تقرير الوظائف" in text:
        return "📋 عاجل | تقرير الوظائف الأمريكي"
    elif "opec" in text or "أوبك" in text:
        return "🛢️ عاجل | تصريحات من أوبك"
    elif "war" in text or "الحرب" in text or "strike" in text:
        return "💥 عاجل | توترات جيوسياسية"
    else:
        return "📰 عاجل | خبر اقتصادي مؤثر"

def format_message(entry, arabic_source=False):
    title = entry.title.strip()
    description = entry.get("description", "") or ""
    full_text = f"{title} {description}"

    # الترجمة
    if not arabic_source:
        try:
            full_text = translator.translate(full_text, dest='ar').text
        except Exception as e:
            print("⚠️ فشل الترجمة:", e)
            full_text = full_text[:300]

    full_text = clean_text(full_text)

    if len(full_text) > 350:
        full_text = full_text[:350] + "..."

    headline = extract_title(full_text)
    footer = "\n\n📎 [رابط الخبر]({})\n\n📡 قناة السوق الأمريكي العاجلة\nhttps://t.me/USMarketnow".format(entry.link)
    return f"{headline}\n\n{full_text}{footer}"

async def send_news():
    sent_titles = load_sent_titles()
    news_sent = 0
    print("🔍 جاري فحص الأخبار...")

    for url in RSS_FEEDS:
        arabic = is_arabic_feed(url)
        feed = feedparser.parse(url)

        for entry in feed.entries:
            title = entry.title.strip()
            if news_sent >= 5 or not is_recent(entry) or title in sent_titles:
                continue

            content = title + " " + (entry.get("description", "") or "")
            if not is_important(content):
                continue

            msg = format_message(entry, arabic_source=arabic)

            try:
                await bot.send_message(chat_id=CHANNEL, text=msg, parse_mode="Markdown", disable_web_page_preview=True)
                print("✅ أُرسل:", title)
                save_sent_title(title)
                news_sent += 1
                await asyncio.sleep(1)
            except Exception as e:
                print("❌ خطأ في الإرسال:", e)

async def loop_forever():
    while True:
        try:
            await send_news()
        except Exception as e:
            print("❌ خطأ عام:", e)
        await asyncio.sleep(300)

if __name__ == "__main__":
    asyncio.run(loop_forever())
