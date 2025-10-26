import os
import logging
from datetime import datetime, timedelta
from kiteconnect import KiteTicker
from dotenv import load_dotenv
import pandas as pd

ENV_FILE = os.path.join(os.path.dirname(__file__), ".env")
load_dotenv(dotenv_path=ENV_FILE, override=True)
logging.basicConfig(level=logging.INFO)

API_KEY = os.getenv("KITE_API_KEY")
ACCESS_TOKEN = os.getenv("KITE_ACCESS_TOKEN")

NIFTY_50_TOKEN = 256265

# Global vars for candle building
current_candle = None
candle_list = []

def get_candle(timestamp, price):
    minute = timestamp.replace(second=0, microsecond=0)
    return {
        "timestamp": minute,
        "open": price,
        "high": price,
        "low": price,
        "close": price,
    }

def update_candle(candle, price):
    candle["high"] = max(candle["high"], price)
    candle["low"] = min(candle["low"], price)
    candle["close"] = price

def detect_swings(candles):
    if len(candles) < 3:
        return
    prev = candles[-2]
    before = candles[-3]
    after = candles[-1]

    # Swing High
    if prev["high"] > before["high"] and prev["high"] > after["high"]:
        print(f"🟢 Swing High Detected at {prev['timestamp']} – High: {prev['high']}")

    # Swing Low
    if prev["low"] < before["low"] and prev["low"] < after["low"]:
        print(f"🔴 Swing Low Detected at {prev['timestamp']} – Low: {prev['low']}")


def on_ticks(ws, ticks):
    global current_candle, candle_list

    for tick in ticks:
        now = datetime.now()
        price = tick["last_price"]

        if current_candle is None:
            current_candle = get_candle(now, price)

        # Check if we're in a new minute
        if now.replace(second=0, microsecond=0) > current_candle["timestamp"]:
            # Finalize previous candle
            candle_list.append(current_candle)

            if len(candle_list) >= 3:
                detect_swings(candle_list[-3:])  # Check last 3 candles

            # Start a new candle
            current_candle = get_candle(now, price)

        else:
            update_candle(current_candle, price)


def on_connect(ws, response):
    print("✅ WebSocket connected. Subscribing to NIFTY 50...")
    ws.subscribe([NIFTY_50_TOKEN])
    ws.set_mode(ws.MODE_FULL, [NIFTY_50_TOKEN])


def on_close(ws, code, reason):
    print("❌ WebSocket closed:", reason)


ws = KiteTicker(API_KEY, ACCESS_TOKEN)
ws.on_ticks = on_ticks
ws.on_connect = on_connect
ws.on_close = on_close

print("🔌 Connecting to Zerodha WebSocket...")
ws.connect(threaded=False)
