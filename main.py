import asyncio
from telegram import Bot
from langchain_community.tools.yahoo_finance_news import YahooFinanceNewsTool

TOKEN = "8101036051:AAEMbhWIYv22FOMV6pXcAOosEWxsy9v3jfY"
CHANNEL = "@USMarketnow"
bot = Bot(token=TOKEN)

news_tool = YahooFinanceNewsTool()

def extract_title(text):
    if "باول" in text or "Powell" in text:
        return "🟥 عاجل | جيروم باول يتحدث"
    elif "الفائدة" in text or "interest rate" in text:
        return "🟥 عاجل | الفيدرالي الأمريكي"
    elif "البيت الأبيض" in text or "White House" in text:
        return "🏛️ البيت الأبيض"
    elif "ترامب" in text:
        return "🇺🇸 تصريحات ترامب"
    elif "CPI" in text or "التضخم" in text:
        return "📉 بيانات التضخم"
    else:
        return "📰 خبر عاجل عن السوق الأمريكي"

def format_news(text):
    title = extract_title(text)
    lines = text.replace(".", ".\n").replace("–", "-").split("\n")
    body = "\n".join(["- " + l.strip() for l in lines if len(l.strip()) > 0])

    if len(body) > 900:
        body = body[:900] + "..."

    footer = "\n\n📌 قناة السوق الأمريكي العاجلة\nhttps://t.me/USMarketnow"
    return f"{title}\n\n{body}{footer}"

async def send_market_news():
    print("🚀 Fetching market news...")
    try:
        articles = news_tool.run({"query": "stock market US Fed CPI earnings"})
        for art in articles:
            msg = format_news(art)
            await bot.send_message(chat_id=CHANNEL, text=msg)
            await asyncio.sleep(2)
    except Exception as e:
        print(f"Error: {e}")

# لتشغيل الدالة
if __name__ == "__main__":
    asyncio.run(send_market_news())
