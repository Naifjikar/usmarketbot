import asyncio
import feedparser
from telegram import Bot
from datetime import datetime, timedelta
import os

# إعدادات البوت
TOKEN = "8101036051:AAEMbhWIYv22FOMV6pXcAOosEWxsy9v3jfY"
CHANNEL = "@USMarketnow"
bot = Bot(token=TOKEN)

# روابط RSS
RSS_FEEDS = [
    "https://finance.yahoo.com/news/rssindex",
    "https://www.cnbc.com/id/100003114/device/rss/rss.html"
]

# كلمات مفتاحية
KEYWORDS = [
    "باول", "powell", "الفائدة", "interest rate", "رفع الفائدة", "خفض الفائدة",
    "البيت الأبيض", "white house", "ترامب", "biden", "أوبك", "opec", "cpi",
    "التضخم", "inflation", "jobs report", "تقرير الوظائف", "nfp", "federal reserve",
    "fed", "سوق العمل", "الذهب", "الدولار", "الفيدرالي", "انكماش", "ركود"
]

# ملف لمنع التكرار
SENT_FILE = "sent_titles.txt"

def load_sent_titles():
    if not os.path.exists(SENT_FILE):
        return set()
    with open(SENT_FILE, "r", encoding="utf-8") as f:
        return set(line.strip() for line in f)

def save_sent_title(title):
    with open(SENT_FILE, "a", encoding="utf-8") as f:
        f.write(title.strip() + "\n")

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
    elif "cpi" in text or "inflation" in text or "التضخم" in text:
        return "📉 عاجل | بيانات التضخم"
    elif "jobs report" in text or "nfp" in text or "تقرير الوظائف" in text:
        return "📋 عاجل | تقرير الوظائف الأمريكي"
    elif "opec" in text or "أوبك" in text:
        return "🛢️ عاجل | تصريحات من أوبك"
    else:
        return "📰 عاجل | خبر هام عن السوق الأمريكي"

def is_important(text):
    lowered = text.lower()
    if not any(keyword in lowered for keyword in KEYWORDS):
        return False
    if not any('\u0600' <= ch <= '\u06FF' for ch in text):  # استبعاد الإنجليزي فقط
        return False
    return True

def is_recent(entry):
    if not hasattr(entry, 'published_parsed'):
        return False
    pub_time = datetime(*entry.published_parsed[:6])
    return pub_time > datetime.utcnow() - timedelta(hours=1)

def format_news(entry):
    description = entry.get("description", "")
    full_text = f"{entry.title} {description}".strip()
    title = extract_title(full_text)
    content = entry.title.strip()
    if len(content) > 180:
        content = content[:180] + "..."
    footer = "\n\n📌 قناة السوق الأمريكي العاجلة 🚨\nhttps://t.me/USMarketnow"
    return f"{title}\n\n{content}{footer}"

async def send_market_news():
    print("🚀 بدأ فحص الأخبار المهمة...")
    sent_titles = load_sent_titles()
    news_sent = 0

    for url in RSS_FEEDS:
        if news_sent >= 3:
            break
        feed = feedparser.parse(url)
        for entry in feed.entries:
            if news_sent >= 3:
                break
            if not is_recent(entry):
                continue
            if entry.title.strip() in sent_titles:
                continue
            full_text = entry.title + " " + entry.get("description", "")
            if not is_important(full_text):
                continue
            msg = format_news(entry)
            await bot.send_message(chat_id=CHANNEL, text=msg, disable_web_page_preview=True)
            save_sent_title(entry.title.strip())
            news_sent += 1
            await asyncio.sleep(1)

if __name__ == "__main__":
    asyncio.run(send_market_news())
