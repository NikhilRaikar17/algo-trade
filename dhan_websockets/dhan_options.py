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
CSV_PATH = os.path.join(
    os.path.dirname(__file__), "..", "Dependencies", "all_instrument 2026-03-24.csv"
)
df = pd.read_csv(CSV_PATH)

# ================= FILTER NIFTY 50 OPTIONS =================
# Dhan CSV columns: SEM_EXM_EXCH_ID, SEM_SMST_SECURITY_ID, SEM_TRADING_SYMBOL,
#                   SEM_EXPIRY_DATE, SEM_STRIKE_PRICE, SEM_OPTION_TYPE, SEM_INSTRUMENT_NAME
nifty_opt = df[
    (df["SEM_EXM_EXCH_ID"] == "NSE")
    & (df["SEM_INSTRUMENT_NAME"] == "OPTIDX")
    & (df["SEM_TRADING_SYMBOL"].str.startswith("NIFTY-"))
    & (~df["SEM_TRADING_SYMBOL"].str.startswith("NIFTYNXT"))
    & (df["SEM_OPTION_TYPE"].isin(["CE", "PE"]))
].copy()

print(f"NIFTY options found before expiry filter: {len(nifty_opt)}")

# ================= PICK NEAREST EXPIRY =================
nifty_opt["expiry"] = pd.to_datetime(nifty_opt["SEM_EXPIRY_DATE"])

today = pd.Timestamp.today().normalize()
future_expiries = sorted(nifty_opt[nifty_opt["expiry"] >= today]["expiry"].unique())

if len(future_expiries) == 0:
    raise ValueError("No upcoming expiries found.")

nearest_expiry = future_expiries[0]
print(f"Nearest expiry selected: {nearest_expiry.date()}")

nifty_opt = nifty_opt[nifty_opt["expiry"] == nearest_expiry].copy()
print(f"Contracts for nearest expiry: {len(nifty_opt)}")

# ================= GET LIVE NIFTY SPOT PRICE =================
NIFTY50_SECURITY_ID = "13"

try:
    quote = dhan.get_market_feed_scrip(
        exchange_segment=dhan.NSE, security_id=NIFTY50_SECURITY_ID, market_depth=False
    )
    nifty_price = quote["data"]["ltp"]
    print(f"Live NIFTY 50 price fetched: {nifty_price}")
except Exception as e:
    nifty_price = 22450
    print(f"Could not fetch live price ({e}), using fallback: {nifty_price}")


# ================= COMPUTE ATM =================
def get_atm(price, step=50):
    return round(price / step) * step


atm = get_atm(nifty_price, step=50)
print(f"ATM strike: {atm}")

CONTRACTS = 0
lower = atm - CONTRACTS
upper = atm + CONTRACTS

nifty_opt = nifty_opt[
    (nifty_opt["SEM_STRIKE_PRICE"] >= lower) & (nifty_opt["SEM_STRIKE_PRICE"] <= upper)
].copy()

print(f"Contracts after ±{CONTRACTS} strike filter: {len(nifty_opt)}")

if nifty_opt.empty:
    raise ValueError("No contracts matched. Check strike range.")

# ================= BUILD INSTRUMENT LIST FOR WEBSOCKET =================
instruments = [
    (marketfeed.NSE_FNO, str(int(row["SEM_SMST_SECURITY_ID"])), marketfeed.Ticker)
    for _, row in nifty_opt.iterrows()
]

# security_id -> contract name lookup
sid_to_name = {
    int(row["SEM_SMST_SECURITY_ID"]): row["SEM_TRADING_SYMBOL"]
    for _, row in nifty_opt.iterrows()
}

print(f"\nContracts subscribed ({len(instruments)}):")
for sid, name in sorted(sid_to_name.items()):
    print(f"  {name}  (security_id={sid})")


# ================= WEBSOCKET FEED =================
def run_feed():
    print("\nConnecting to Dhan market feed...")

    feed = marketfeed.DhanFeed(CLIENT_ID, ACCESS_TOKEN, instruments, version="v2")
    feed.run_forever()

    print("WebSocket connected. Streaming live premiums...\n")

    while True:
        data = feed.get_data()
        if data:
            security_id = data.get("security_id")
            ltp = data.get("LTP") or data.get("last_price")
            if security_id and ltp:
                name = sid_to_name.get(int(float(security_id)), str(security_id))
                print(f"  {name:35s}  LTP: {ltp}")


# ================= ENTRY POINT =================
if __name__ == "__main__":
    try:
        run_feed()
    except KeyboardInterrupt:
        print("\nStopped by user.")
