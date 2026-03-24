import os
import pandas as pd
from dotenv import load_dotenv
from dhanhq import dhanhq, marketfeed

# ================= ENV =================
ENV_FILE = os.path.join(os.path.dirname(__file__), "..", ".env")
load_dotenv(dotenv_path=ENV_FILE, override=True)

CLIENT_ID = os.getenv("DHAN_CLIENT_CODE")
ACCESS_TOKEN = os.getenv("DHAN_TOKEN_ID")

dhan = dhanhq(CLIENT_ID, ACCESS_TOKEN)

# ================= LOAD INSTRUMENT MASTER =================
CSV_PATH = os.path.join(os.path.dirname(__file__), "..", "all_instruments.csv")
df = pd.read_csv(CSV_PATH)

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
CONTRACTS = 500
# ================= FILTER ± 500 POINTS AROUND ATM =================
# Keeping range at ±500 (20 strikes × 2 = ~40 instruments) to stay
# within Dhan WebSocket's ~100 instrument per connection limit.
lower = atm - CONTRACTS
upper = atm + CONTRACTS

nifty_opt = nifty_opt[
    (nifty_opt["strike"] >= lower) & (nifty_opt["strike"] <= upper)
].copy()

print(f"Contracts after ±500 strike filter: {len(nifty_opt)}")

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

# TEST: add known-working instrument from dhan_ws.py to confirm feed is alive
instruments.append((marketfeed.NSE, "11536", marketfeed.Ticker))

# Lookup: security_id (int) -> contract name
sid_to_name = {
    int(row["instrument_token"]): row["tradingsymbol"]
    for _, row in nifty_opt.iterrows()
}

print(f"\nTotal instruments to subscribe: {len(instruments)}")
print("Contracts subscribed:")
for sid, name in sid_to_name.items():
    print(f"  {name}  (security_id={sid})")

# ================= WEBSOCKET FEED =================

def run_feed():
    """Connect to Dhan websocket and stream live option premiums."""
    print("\nConnecting to Dhan market feed...")

    feed = marketfeed.DhanFeed(CLIENT_ID, ACCESS_TOKEN, instruments, version="v2")
    feed.run_forever()  # blocks until connected

    print("WebSocket connected. Streaming live premiums...\n")

    while True:
        data = feed.get_data()
        if data:
            security_id = data.get("security_id")
            ltp = data.get("LTP") or data.get("last_price")
            if security_id and ltp:
                name = sid_to_name.get(int(float(security_id)), str(security_id))
                print(f"  {name:30s}  LTP: {ltp}")


# ================= ENTRY POINT =================
if __name__ == "__main__":
    try:
        run_feed()
    except KeyboardInterrupt:
        print("\nStopped by user.")
