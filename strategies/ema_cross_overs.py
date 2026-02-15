import os
import logging
from datetime import datetime
from kiteconnect import KiteTicker
from dotenv import load_dotenv
import pandas as pd

ENV_FILE = os.path.join(os.path.dirname(__file__), ".env")
load_dotenv(dotenv_path=ENV_FILE, override=True)
logging.basicConfig(level=logging.INFO)

API_KEY = os.getenv("KITE_API_KEY")
ACCESS_TOKEN = os.getenv("KITE_ACCESS_TOKEN")

instrument_token = 256265
symbol = "NIFTY24OCTFUT"
lot_size = 50


df = pd.DataFrame(columns=["timestamp", "price"])
trades = []
position = None


def record_trade(action, price):
    global trades, position
    ts = datetime.now()

    if action == "BUY":
        if position is None:
            position = {"side": "BUY", "entry_price": price, "qty": lot_size}
            trades.append({"time": ts, "action": "BUY", "price": price, "pnl": 0})
        elif position["side"] == "SELL":  # close short
            pnl = (position["entry_price"] - price) * lot_size
            trades.append(
                {"time": ts, "action": "BUY (cover)", "price": price, "pnl": pnl}
            )
            position = None

    elif action == "SELL":
        if position is None:
            position = {"side": "SELL", "entry_price": price, "qty": lot_size}
            trades.append({"time": ts, "action": "SELL", "price": price, "pnl": 0})
        elif position["side"] == "BUY":
            pnl = (price - position["entry_price"]) * lot_size
            trades.append(
                {"time": ts, "action": "SELL (exit)", "price": price, "pnl": pnl}
            )
            position = None


def on_ticks(ws, ticks):
    global df
    tick = ticks[0]
    price = tick["last_price"]
    ts = pd.Timestamp.now()

    df.loc[len(df)] = [ts, price]

    if len(df) > 300:
        df = df.iloc[-300:]

    df["ema50"] = df["price"].ewm(span=50, adjust=False).mean()
    df["ema100"] = df["price"].ewm(span=100, adjust=False).mean()

    if len(df) > 100:
        prev_ema50, prev_ema100 = df["ema50"].iloc[-2], df["ema100"].iloc[-2]
        curr_ema50, curr_ema100 = df["ema50"].iloc[-1], df["ema100"].iloc[-1]

        if prev_ema50 < prev_ema100 and curr_ema50 > curr_ema100:
            print("🚀 BUY Signal at", price)
            record_trade("BUY", price)

        elif prev_ema50 > prev_ema100 and curr_ema50 < curr_ema100:
            print("🔻 SELL Signal at", price)
            record_trade("SELL", price)


def on_connect(ws, response):
    ws.subscribe([instrument_token])
    ws.set_mode(ws.MODE_FULL, [instrument_token])


def on_close(ws, code, reason):
    print("WebSocket closed", code, reason)
    export_trades()


def export_trades():
    global trades
    df_trades = pd.DataFrame(trades)
    filename = f"paper_trades_{datetime.now().strftime('%Y%m%d')}.xlsx"
    df_trades.to_excel(filename, index=False)
    print(f"✅ Trades exported to {filename}")


kws = KiteTicker(API_KEY, ACCESS_TOKEN)
kws.on_ticks = on_ticks
kws.on_connect = on_connect
kws.on_close = on_close

print("📡 Starting paper trading...")
kws.connect(threaded=True)
