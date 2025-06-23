import asyncio
import feedparser
from telegram import Bot
from datetime import datetime, timedelta
import os
from googletrans import Translator

print("✅ Bot is starting...")

# إعدادات البوت
TOKEN = "8101036051:AAEMbhWIYv22FOMV6pXcAOosEWxsy9v3jfY"
CHANNEL = "@USMarketnow"
bot = Bot(token=TOKEN)

translator = Translator()

# روابط RSS
RSS_FEEDS = [
    "https://finance.yahoo.com/news/rssindex",
    "https://www.cnbc.com/id/100003114/device/rss/rss.html"
]

# كلمات مفتاحية إضافية
KEYWORDS = [
    "باول", "الفائدة", "رفع الفائدة", "خفض الفائدة", "البيت الأبيض", "ترامب", "بايدن",
    "أوبك", "cpi", "التضخم", "تقرير الوظائف", "الفيدرالي", "الركود", "الانكماش",
    "سوق العمل", "الذهب", "الدولار", "البطالة", "الكونغرس", "الرئيس الأمريكي",
    "الانتخابات", "ضربة", "هجوم", "قصف", "إيران", "إسرائيل", "النفط", "أرباح", "الحرب",
    "سباكس", "spx", "مؤشر سباكس", "s&p500", "داو", "الداو", "الداو جونز",
    "السوق الأمريكي", "الأسهم الأمريكية", "الأسواق الأمريكية", "البورصة الأمريكية",
    "الاقتصاد الأمريكي", "هبوط السوق", "ارتفاع السوق", "وول ستريت"
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
    elif "war" in text or "الحرب" in text or "strike" in text or "قصف" in text:
        return "💥 عاجل | توترات جيوسياسية"
    else:
        return "📰 عاجل | خبر هام عن السوق الأمريكي"

def is_important(text):
    for keyword in KEYWORDS:
        if keyword.lower() in text.lower():
            print(f"✅ كلمة مطابقة: {keyword}")
            return True
    return False

def is_recent(entry):
    if not hasattr(entry, 'published_parsed'):
        return True
    pub_time = datetime(*entry.published_parsed[:6])
    return pub_time > datetime.utcnow() - timedelta(hours=2)

def format_news(entry):
    description = entry.get("description", "")
    full_text = f"{entry.title} {description}".strip()

    try:
        translated = translator.translate(full_text, dest='ar').text
    except Exception as e:
        print("⚠️ فشل الترجمة:", e)
        translated = full_text[:350]

    if len(translated) > 350:
        translated = translated[:350] + "..."

    title = extract_title(full_text)
    footer = "\n\n📌 قناة السوق الأمريكي العاجلة 🚨\nhttps://t.me/USMarketnow"
    return f"{title}\n\n{translated}{footer}"

async def send_market_news():
    print("🔍 Checking RSS feeds...")
    sent_titles = load_sent_titles()
    news_sent = 0

    for url in RSS_FEEDS:
        print(f"📡 Fetching feed: {url}")
        if news_sent >= 3:
            break
        feed = feedparser.parse(url)
        for entry in feed.entries:
            if news_sent >= 3:
                break
            if not is_recent(entry):
                print(f"⏱️ Ignored (old): {entry.title}")
                continue
            if entry.title.strip() in sent_titles:
                print(f"🔁 Already sent: {entry.title}")
                continue

            full_text = entry.title + " " + entry.get("description", "")
            if not is_important(full_text):
                print(f"❌ Not important: {entry.title}")
                continue

            msg = format_news(entry)
            print(f"📨 Sending: {entry.title}")
            await bot.send_message(chat_id=CHANNEL, text=msg, disable_web_page_preview=True)
            save_sent_title(entry.title.strip())
            news_sent += 1
            await asyncio.sleep(1)

# تنفيذ مباشر لتجربة فورية
if __name__ == "__main__":
    asyncio.run(send_market_news())
