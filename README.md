import os
import time
from telegram import Bot
from langchain_community.tools.yahoo_finance_news import YahooFinanceNewsTool

TOKEN = "8101036051:AAEMbhWIYv22FOMV6pXcAOosEWxsy9v3jfY"
CHANNEL = "@USMarketnow"
bot = Bot(token=TOKEN)

# إعداد أداة الأخبار
news_tool = YahooFinanceNewsTool()

def format_news(text):
    short_text = text.strip()
    if len(short_text) > 300:
        short_text = short_text[:300] + "..."
    footer = "\n\nقناة السوق الأمريكي العاجلة 🚨\nhttps://t.me/USMarketnow"
    return short_text + footer

def send_market_news():
    print("🔔 Fetching Market News from Yahoo Finance …")
    try:
        articles = news_tool.run({"query": "stock market US Fed CPI earnings"})
        print(f"🗞️ Retrieved {len(articles)} articles")
        for art in articles:
            title = art.get("title", "")
            summary = art.get("summary", "")
            msg = f"📰 {title}\n{summary}"
            bot.send_message(chat_id=CHANNEL, text=format_news(msg))
            time.sleep(1)
        print("✅ Market news sent.")
    except Exception as e:
        print("❌ Error fetching news:", e)

if __name__ == "__main__":
    send_market_news()
