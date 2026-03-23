import os
import pandas as pd
from dotenv import load_dotenv
from dhanhq import dhanhq, marketfeed
import time

# ================= ENV =================
ENV_FILE = os.path.join(os.path.dirname(__file__), "..", ".env")
load_dotenv(dotenv_path=ENV_FILE, override=True)

CLIENT_ID = os.getenv("DHAN_CLIENT_CODE")
ACCESS_TOKEN = os.getenv("DHAN_TOKEN_ID")

dhan = dhanhq(CLIENT_ID, ACCESS_TOKEN)

# ================= LOAD INSTRUMENT MASTER =================
df = pd.read_csv("../instruments.csv")

print("Columns found:", df.columns.tolist())
print("Unique segments:", df["segment"].unique())
print("Unique exchanges:", df["exchange"].unique())

# ================= FILTER NIFTY 50 OPTIONS =================
# NIFTY 50 options live in NFO exchange, segment NFO-OPT, instrument_type CE/PE
# Symbol starts with "NIFTY" but NOT "BANKNIFTY", "FINNIFTY", etc.
nifty_opt = df[
    (df["exchange"] == "NFO")
    & (df["instrument_type"].isin(["CE", "PE"]))
    & (df["tradingsymbol"].str.startswith("NIFTY"))
    & (~df["tradingsymbol"].str.startswith("NIFTYBEE"))  # exclude ETFs
    & (~df["tradingsymbol"].str.startswith("NIFTYINDIAMANUFACTURING"))
    # Exclude BANKNIFTY, MIDCPNIFTY, FINNIFTY, NIFTYNXT50, etc.
    & (df["name"].str.upper() == "NIFTY 50")
].copy()

if nifty_opt.empty:
    # Fallback: some CSVs store name as "NIFTY" not "NIFTY 50"
    nifty_opt = df[
        (df["exchange"] == "NFO")
        & (df["instrument_type"].isin(["CE", "PE"]))
        & (df["name"].str.upper().isin(["NIFTY 50", "NIFTY"]))
    ].copy()

print(f"\nNIFTY options found before expiry filter: {len(nifty_opt)}")

# ================= PICK NEAREST WEEKLY EXPIRY =================
nifty_opt["expiry"] = pd.to_datetime(nifty_opt["expiry"])

today = pd.Timestamp.today().normalize()
future_expiries = sorted(nifty_opt[nifty_opt["expiry"] >= today]["expiry"].unique())

if len(future_expiries) == 0:
    raise ValueError("No upcoming expiries found. Check your instruments.csv date.")

nearest_expiry = future_expiries[0]
print(f"Nearest expiry selected: {nearest_expiry.date()}")

nifty_opt = nifty_opt[nifty_opt["expiry"] == nearest_expiry].copy()
print(f"Contracts for nearest expiry: {len(nifty_opt)}")

# ================= GET LIVE NIFTY SPOT PRICE =================
# Fetch live LTP for NIFTY 50 index via Dhan API
# Index security ID for NIFTY 50 on NSE is 13 (Dhan standard)
NIFTY50_SECURITY_ID = "13"

try:
    quote = dhan.get_market_feed_scrip(
        exchange_segment=dhan.NSE, security_id=NIFTY50_SECURITY_ID, market_depth=False
    )
    nifty_price = quote["data"]["ltp"]
    print(f"Live NIFTY 50 price fetched: {nifty_price}")
except Exception as e:
    # Fallback to a hardcoded price for testing
    nifty_price = 22450
    print(f"Could not fetch live price ({e}), using fallback: {nifty_price}")


# ================= COMPUTE ATM =================
def get_atm(price, step=50):
    """Round to nearest strike step."""
    return round(price / step) * step


atm = get_atm(nifty_price, step=50)
print(f"ATM strike: {atm}")

# ================= FILTER ± 2000 POINTS AROUND ATM =================
lower = atm - 2000
upper = atm + 2000

nifty_opt = nifty_opt[
    (nifty_opt["strike"] >= lower) & (nifty_opt["strike"] <= upper)
].copy()

print(f"Contracts after ±2000 strike filter: {len(nifty_opt)}")

if nifty_opt.empty:
    raise ValueError("No contracts matched. Check strike column values in your CSV.")

# ================= DISPLAY SNAPSHOT =================
display = nifty_opt[
    [
        "tradingsymbol",
        "instrument_token",
        "strike",
        "instrument_type",
        "expiry",
        "last_price",
    ]
].copy()
display = display.sort_values(["strike", "instrument_type"])
print("\n--- Option Chain Snapshot (last_price from CSV, not live) ---")
print(display.to_string(index=False))

# ================= BUILD INSTRUMENT LIST FOR WEBSOCKET =================
# Dhan marketfeed expects: (exchange_segment, security_id_string, subscription_type)
# instrument_token in Kite CSV = security_id in Dhan feed
instruments = []
for _, row in nifty_opt.iterrows():
    instruments.append(
        (
            marketfeed.NSE_FNO,  # exchange segment for NFO
            str(int(row["instrument_token"])),  # security ID as string
            marketfeed.Ticker,  # Ticker = LTP only; use Quote for full quote
        )
    )

print(f"\nTotal instruments to subscribe: {len(instruments)}")

# ================= WEBSOCKET FEED =================
# In-memory store of latest LTPs keyed by security_id
ltp_store = {}


def process_tick(data):
    """Process a single tick from the feed."""
    security_id = str(data.get("security_id", ""))
    ltp = data.get("LTP") or data.get("last_price")

    if not ltp or not security_id:
        return

    ltp_store[security_id] = ltp

    # Look up symbol details from our filtered DataFrame
    row = nifty_opt[nifty_opt["instrument_token"].astype(str) == security_id]
    if not row.empty:
        symbol = row.iloc[0]["tradingsymbol"]
        strike = row.iloc[0]["strike"]
        opt_type = row.iloc[0]["instrument_type"]
        print(f"  {symbol:30s}  Strike: {strike:7.0f}  {opt_type}  LTP: {ltp}")


def run_feed():
    """Connect to Dhan websocket and poll for live option premiums."""
    print("\nConnecting to Dhan market feed...")

    feed = marketfeed.DhanFeed(CLIENT_ID, ACCESS_TOKEN, instruments, version="v2")
    feed.run_forever()  # opens the websocket connection (non-blocking)

    print("WebSocket connected. Streaming live premiums...\n")

    try:
        while True:
            data = feed.get_data()
            if data:
                process_tick(data)
            time.sleep(0.1)
    except KeyboardInterrupt:
        print("\nFeed stopped by user.")
        feed.disconnect()


# ================= ENTRY POINT =================
if __name__ == "__main__":
    run_feed()
