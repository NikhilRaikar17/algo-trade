import time
from dhanhq import dhanhq
from dhanhq import marketfeed
from dhanhq import orderupdate
import os
from dotenv import load_dotenv

ENV_FILE = os.path.join(os.path.dirname(__file__), ".env")
load_dotenv(dotenv_path=ENV_FILE, override=True)
CLIENT_ID = os.getenv("DHAN_CLIENT_CODE")
ACCESS_TOKEN = os.getenv("DHAN_TOKEN_ID")

# REST & Websocket client
dhan = dhanhq(CLIENT_ID, ACCESS_TOKEN)

# ================= LIVE MARKET FEED =================

# Prepare subscriptions: list of tuples
# (exchange_segment, security_id, subscription_type)
instruments = [
    (marketfeed.NSE, "11536", marketfeed.Ticker),  # Ticker data
    (marketfeed.NSE, "11915", marketfeed.Full),  # Full depth/quote
]

# Create the feed connection
feed_conn = marketfeed.DhanFeed(CLIENT_ID, ACCESS_TOKEN, instruments, version="v2")

# ================= LIVE ORDER UPDATE =================


def run_order_update():
    order_conn = orderupdate.OrderSocket(CLIENT_ID, ACCESS_TOKEN)
    while True:
        try:
            order_conn.connect_to_dhan_websocket_sync()
        except Exception as e:
            print("Reconnect WS:", e)
            time.sleep(5)


# ================= MAIN LOOP =================

try:
    # Start market feed forever loop (blocking)
    feed_conn.run_forever()
    # You can also get data with .get_data() after each loop
    while True:
        data = feed_conn.get_data()
        print("Market Feed:", data)

except KeyboardInterrupt:
    print("Stopping feeds…")
    feed_conn.disconnect()
