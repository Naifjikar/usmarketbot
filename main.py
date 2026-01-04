import asyncio, requests, time, json, os, re
from telegram import Bot

# ====== CONFIG ======
TOKEN = "8101036051:AAEMbhWIYv22FOMV6pXcAOosEWxsy9v3jfY"
CHANNEL = "@USMarketnow"
POLYGON_KEY = "ht3apHm7nJA2VhvBynMHEcpRI11VSRbq"

PRICE_MIN, PRICE_MAX = 0.01, 10.0
INTERVAL = 180
STATE_FILE = "news_state.json"

bot = Bot(token=TOKEN)

# ====== TRANSLATION ======
try:
    from deep_translator import GoogleTranslator
    tr = GoogleTranslator(source="auto", target="ar")
    translate = lambda x: tr.translate(x) if x else ""
except:
    translate = lambda x: x or ""

# ====== STATE ======
state = json.load(open(STATE_FILE)) if os.path.exists(STATE_FILE) else {}

def save_state():
    json.dump(state, open(STATE_FILE, "w"))

# ====== POLYGON ======
def pg(path, params=None):
    params = params or {}
    params["apiKey"] = POLYGON_KEY
    return requests.get("https://api.polygon.io"+path, params=params, timeout=20).json()

def price(symbol):
    try:
        p = pg(f"/v2/snapshot/locale/us/markets/stocks/tickers/{symbol}")
        return float(p["ticker"]["day"]["c"])
    except:
        return None

# ====== BOT LOOP ======
async def run():
    while True:
        try:
            news = pg("/v2/reference/news", {"limit": 30}).get("results", [])
            for n in news:
                for sym in n.get("tickers", [])[:5]:
                    if not re.match(r"^[A-Z.-]{1,10}$", sym): 
                        continue
                    p = price(sym)
                    if not p or not (PRICE_MIN <= p <= PRICE_MAX):
                        continue

                    uid = f"{n.get('id')}:{sym}"
                    if uid in state:
                        continue

                    msg = (
                        f"🚨 <b>{sym}</b> | ${p:.2f}\n"
                        f"📰 {translate(n.get('title'))}\n"
                        f"🔗 {n.get('article_url','')}"
                    )

                    await bot.send_message(CHANNEL, msg, parse_mode="HTML")
                    state[uid] = time.time()
                    save_state()
                    await asyncio.sleep(1)

        except Exception as e:
            print("ERR:", e)

        await asyncio.sleep(INTERVAL)

asyncio.run(run())
