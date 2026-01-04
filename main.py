#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
USMarketnow - News Bot
Source: Finnhub (مصدر واحد)
- أخبار السوق الأمريكي + أخبار الأسهم
- فلترة السعر من 0.01$ إلى 10$
- ترجمة تلقائية للعربية
- إرسال إلى تيليجرام
- منع تكرار الأخبار
"""

import asyncio
import json
import os
import re
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import requests
from telegram import Bot

# ================== الإعدادات والمفاتيح ==================

TOKEN = "8101036051:AAEMbhWIYv22FOMV6pXcAOosEWxsy9v3jfY"
CHANNEL = "@USMarketnow"
bot = Bot(token=TOKEN)

FINNHUB_API_KEY = "d1dqgr9r01qpp0b3fligd1dqgr9r01qpp0b3flj0"

PRICE_MIN = 0.01
PRICE_MAX = 10.00

POLL_SECONDS = 180          # كل 3 دقائق
MAX_ARTICLES_PER_POLL = 40

STATE_FILE = "sent_news_state.json"

# =========================================================


# ================== الترجمة ==================
def _get_translator():
    try:
        from deep_translator import GoogleTranslator
        return ("deep", GoogleTranslator(source="auto", target="ar"))
    except Exception:
        try:
            from googletrans import Translator
            return ("google", Translator())
        except Exception:
            return (None, None)

_TRANSLATOR_KIND, _TRANSLATOR = _get_translator()


def translate_to_ar(text: str) -> str:
    text = (text or "").strip()
    if not text or _TRANSLATOR is None:
        return text
    try:
        if _TRANSLATOR_KIND == "deep":
            return _TRANSLATOR.translate(text)
        return _TRANSLATOR.translate(text, dest="ar").text
    except Exception:
        return text
# ============================================


# ================== منع التكرار ==================
def load_state() -> Dict[str, float]:
    if not os.path.exists(STATE_FILE):
        return {}
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(state: Dict[str, float]) -> None:
    cutoff = time.time() - 30 * 24 * 3600
    state = {k: v for k, v in state.items() if v >= cutoff}
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
# =================================================


# ================== Finnhub ==================
BASE = "https://finnhub.io/api/v1"

def finnhub_get(path: str, params: Optional[dict] = None):
    params = params or {}
    params["token"] = FINNHUB_API_KEY
    r = requests.get(f"{BASE}{path}", params=params, timeout=25)
    r.raise_for_status()
    return r.json()


def get_general_news() -> List[dict]:
    data = finnhub_get("/news", {"category": "general"})
    return data[:MAX_ARTICLES_PER_POLL] if isinstance(data, list) else []


_price_cache: Dict[str, Tuple[float, float]] = {}

def get_price(symbol: str) -> Optional[float]:
    symbol = symbol.upper().strip()
    if not re.fullmatch(r"[A-Z.\-]{1,10}", symbol):
        return None

    now = time.time()
    if symbol in _price_cache and now - _price_cache[symbol][1] < 60:
        return _price_cache[symbol][0]

    try:
        q = finnhub_get("/quote", {"symbol": symbol})
        price = float(q.get("c") or 0)
        if price > 0:
            _price_cache[symbol] = (price, now)
            return price
    except Exception:
        pass
    return None
# =================================================


# ================== تنسيق الرسالة ==================
def clean(text: str, max_len: int) -> str:
    text = re.sub(r"\s+", " ", (text or "").strip())
    return text if len(text) <= max_len else text[:max_len - 1] + "…"


def build_message(symbol: str, price: float, title_ar: str, summary_ar: str, url: str) -> str:
    msg = [
        f"🚨 <b>{symbol}</b> | ${price:.2f}",
        f"📰 {clean(title_ar, 220)}"
    ]
    if summary_ar:
        msg.append(f"🧾 {clean(summary_ar, 320)}")
    msg.append(f"🔗 {url}")
    return "\n".join(msg)
# =================================================


async def send_telegram(html: str):
    await bot.send_message(
        chat_id=CHANNEL,
        text=html,
        parse_mode="HTML",
        disable_web_page_preview=False
    )


def extract_tickers(article: dict) -> List[str]:
    related = article.get("related", "")
    tickers = [t.strip().upper() for t in related.split(",") if t.strip()]
    return list(dict.fromkeys(tickers))


async def poll_once(state: Dict[str, float]) -> int:
    sent = 0
    news = await asyncio.to_thread(get_general_news)

    for art in news:
        art_id = art.get("id")
        headline = art.get("headline", "")
        summary = art.get("summary", "")
        url = art.get("url", "")
        dt = art.get("datetime", 0)

        tickers = extract_tickers(art)
        if not tickers:
            continue

        headline_ar = translate_to_ar(headline)
        summary_ar = translate_to_ar(summary)

        for sym in tickers[:8]:
            price = await asyncio.to_thread(get_price, sym)
            if price is None or not (PRICE_MIN <= price <= PRICE_MAX):
                continue

            uid = f"{art_id}:{sym}:{dt}"
            if uid in state:
                continue

            msg = build_message(sym, price, headline_ar, summary_ar, url)
            await send_telegram(msg)
            state[uid] = time.time()
            sent += 1
            await asyncio.sleep(1.2)

    return sent


async def main():
    print("✅ USMarketnow News Bot started")
    state = load_state()

    while True:
        try:
            sent = await poll_once(state)
            if sent:
                save_state(state)
                print(f"✅ Sent {sent} news @ {datetime.now()}")
        except Exception as e:
            print("⚠️ Error:", e)

        await asyncio.sleep(POLL_SECONDS)


if __name__ == "__main__":
    asyncio.run(main())
