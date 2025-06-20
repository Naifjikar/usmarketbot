import asyncio
import feedparser
import requests
from bs4 import BeautifulSoup
from telegram import Bot
import telegram.error
import datetime

# توكن البوت وقناة النشر
TOKEN = "8101036051:AAEMbhWIYv22FOMV6pXcAOosEWxsy9v3jfY"
CHANNEL = "@USMarketnow"
bot = Bot(token=TOKEN)

# المصادر الرئيسية
RSS_FEEDS = [
    "https://finance.yahoo.com/news/rssindex",
    "https://www.cnbc.com/id/100003114/device/rss/rss.html"
]

# الكلمات المفتاحية المهمة
KEYWORDS = [
    "باول", "powell", "الفائدة", "interest rate", "رفع الفائدة", "خفض الفائدة",
    "البيت الأبيض", "white house", "ترامب", "biden", "أوبك", "opec", "cpi",
    "التضخم", "inflation", "jobs report", "تقرير الوظائف", "nfp", "federal reserve",
    "fed", "earnings", "سوق العمل", "الذهب", "الدولار", "الفيدرالي", "انكماش", "ركود"
]

# استخراج التصنيف المناسب للخبر
def extract_title(text):
    text = text.lower()
    if "powell" in text or "باول" in text:
        return "🟥 عاجل | جيروم باول يتحدث"
    elif "interest rate" in text or "الفائدة" in text:
        return "🟥 عاجل | الفيدرالي الأمريكي"
    elif "white house" in text or "البيت الأبيض" in text:
        return "🏛️ البيت الأبيض"
    elif "trump" in text or "ترامب" in text:
        return "🇺🇸 تصريحات ترامب"
    elif "cpi" in text or "inflation" in text or "التضخم" in text:
        return "📉 بيانات التضخم"
    elif "earnings" in text:
        return "📊 نتائج أرباح الشركات"
    elif "jobs report" in text or "nfp" in text or "تقرير الوظائف" in text:
        return "📋 تقرير الوظائف الأمريكي"
    else:
        return "📰 خبر عاجل عن السوق الأمريكي"

# هل الخبر يحتوي على كلمات مهمة
def is_important(text):
    lowered = text.lower()
    return any(keyword in lowered for keyword in KEYWORDS)

# تهيئة الرسالة
def format_news(entry):
    desc = getattr(entry, 'description', '')
    title = extract_title(entry.title + desc)
    content = entry.title.strip()
    if len(content) > 900:
        content = content[:900] + "..."
    footer = "\n\n📌 قناة السوق الأمريكي العاجلة\nhttps://t.me/USMarketnow"
    return f"{title}\n\n- {content}{footer}"

# إرسال آمن مع إعادة المحاولة في حال حدوث Timeout
async def safe_send(text):
    try:
        await bot.send_message(chat_id=CHANNEL, text=text)
    except telegram.error.TimedOut:
        print("⏳ إعادة المحاولة بعد خطأ Timeout")
        await asyncio.sleep(5)
        await bot.send_message(chat_id=CHANNEL, text=text)

# جلب الأخبار الاقتصادية من investing.com
def fetch_economic_events():
    url = "https://www.investing.com/economic-calendar/"
    headers = {"User-Agent": "Mozilla/5.0"}
    events = []

    try:
        response = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(response.content, "html.parser")

        for row in soup.select("tr.js-event-item"):
            impact = row.select_one(".sentiment")
            if impact and len(impact.select("i.grayFullBullishIcon")) < 3:
                continue

            time = row.get("data-event-datetime")
            country = row.get("data-country")
            title = row.get("data-event-name")

            if time and title and "United States" in country:
                events.append(f"⏰ {time} - {title}")

    except Exception as e:
        print(f"❌ Error fetching economic events: {e}")

    return events

# تشغيل البوت الكامل
async def send_market_news():
    print("🚀 بدء فحص الأخبار...")
    sent_titles = set()

    # أخبار RSS
    for url in RSS_FEEDS:
        feed = feedparser.parse(url)
        for entry in feed.entries:
            full_text = entry.title + " " + entry.get("description", "")
            if len(entry.title.strip()) < 20 or entry.title in sent_titles:
                continue
            if not is_important(full_text):
                continue
            msg = format_news(entry)
            await safe_send(msg)
            sent_titles.add(entry.title)
            await asyncio.sleep(2)

    # أخبار اقتصادية من investing
    events = fetch_economic_events()
    if events:
        message = "📊 أخبار اقتصادية أمريكية مهمة اليوم:\n\n" + "\n".join(events[:10])
        message += "\n\n📌 قناة السوق الأمريكي العاجلة\nhttps://t.me/USMarketnow"
        await safe_send(message)

if __name__ == "__main__":
    asyncio.run(send_market_news())
