import os
import sys
import asyncio
import pandas as pd
from datetime import datetime
from dotenv import load_dotenv
from dhanhq import dhanhq, marketfeed
import xlwings as xw

# Fix: COM (xlwings/Excel) conflicts with ProactorEventLoop on Windows.
# SelectorEventLoop works correctly alongside COM objects.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# ================= ENV =================
ENV_FILE = os.path.join(os.path.dirname(__file__), "..", ".env")
load_dotenv(dotenv_path=ENV_FILE, override=True)

CLIENT_ID = os.getenv("DHAN_CLIENT_CODE")
ACCESS_TOKEN = os.getenv("DHAN_TOKEN_ID")

dhan = dhanhq(CLIENT_ID, ACCESS_TOKEN)

# ================= CONFIG =================
STRIKE_RANGE = 0     # ATM only (set to 500 to get ±500 points around ATM)
NUM_EXPIRIES = 1     # 1 = nearest expiry only, 2 = two expiries

# ================= LOAD INSTRUMENT MASTER =================
CSV_PATH = os.path.join(
    os.path.dirname(__file__), "..", "Dependencies", "all_instrument 2026-03-24.csv"
)
df = pd.read_csv(CSV_PATH)

# ================= FILTER NIFTY OPTIONS =================
nifty_opt = df[
    (df["SEM_EXM_EXCH_ID"] == "NSE")
    & (df["SEM_INSTRUMENT_NAME"] == "OPTIDX")
    & (df["SEM_TRADING_SYMBOL"].str.startswith("NIFTY-"))
    & (~df["SEM_TRADING_SYMBOL"].str.startswith("NIFTYNXT"))
    & (df["SEM_OPTION_TYPE"].isin(["CE", "PE"]))
].copy()

nifty_opt["expiry"] = pd.to_datetime(nifty_opt["SEM_EXPIRY_DATE"])

# Skip today's and past expiries — only strictly future expiries
today = pd.Timestamp.today().normalize()
nifty_opt = nifty_opt[nifty_opt["expiry"] > today].copy()

# Pick the N nearest expiries
expiries = sorted(nifty_opt["expiry"].unique())[:NUM_EXPIRIES]
if not expiries:
    raise ValueError("No upcoming expiries found.")

nifty_opt = nifty_opt[nifty_opt["expiry"].isin(expiries)].copy()
print(f"Expiries selected: {[e.date() for e in expiries]}")

# ================= GET LIVE NIFTY SPOT =================
try:
    quote = dhan.get_market_feed_scrip(
        exchange_segment=dhan.NSE, security_id="13", market_depth=False
    )
    nifty_price = quote["data"]["ltp"]
    print(f"Live NIFTY price: {nifty_price}")
except Exception as e:
    nifty_price = 22450
    print(f"Could not fetch live price ({e}), using fallback: {nifty_price}")

# ================= ATM + STRIKE FILTER =================
atm = round(nifty_price / 50) * 50
lower = atm - STRIKE_RANGE
upper = atm + STRIKE_RANGE
print(f"ATM: {atm}  |  Strike range: {lower} – {upper}")

nifty_opt = nifty_opt[
    (nifty_opt["SEM_STRIKE_PRICE"] >= lower)
    & (nifty_opt["SEM_STRIKE_PRICE"] <= upper)
].copy()

if nifty_opt.empty:
    raise ValueError("No contracts matched the strike range.")

print(f"Total contracts: {len(nifty_opt)}")

# ================= BUILD WEBSOCKET INSTRUMENTS =================
instruments = [
    (marketfeed.NSE_FNO, str(int(row["SEM_SMST_SECURITY_ID"])), marketfeed.Ticker)
    for _, row in nifty_opt.iterrows()
]

# security_id -> contract name (for console print)
sid_to_name = {
    int(row["SEM_SMST_SECURITY_ID"]): row["SEM_TRADING_SYMBOL"]
    for _, row in nifty_opt.iterrows()
}

# ================= EXCEL SETUP =================
def setup_excel():
    """
    Layout per expiry block:
      Row offset 0 : Expiry header
      Row offset 1 : Strike | CE LTP | PE LTP
      Row offset 2+ : data rows (one per strike)
    Blocks are separated by a blank row.
    Returns a dict: security_id -> (row, col) for direct cell writes.
    """
    app = xw.App(visible=True)
    wb = app.books.add()
    ws = wb.sheets[0]
    ws.name = "NIFTY Options"

    # Title
    ws["A1"].value = f"NIFTY Live Options  |  ATM: {atm}  |  Range: ±{STRIKE_RANGE}"
    ws["A1"].font.bold = True
    ws["A1"].font.size = 13
    ws["A2"].value = "Last updated:"
    ws["A2"].font.bold = True

    ws.range("A:A").column_width = 18
    ws.range("B:B").column_width = 12
    ws.range("C:C").column_width = 12

    sid_to_cell = {}   # security_id -> (excel_row, excel_col)
    current_row = 4    # start writing from row 4

    for expiry in expiries:
        block = nifty_opt[nifty_opt["expiry"] == expiry].copy()
        strikes = sorted(block["SEM_STRIKE_PRICE"].unique())

        # Expiry header
        ws.cells(current_row, 1).value = f"Expiry: {expiry.date()}"
        ws.cells(current_row, 1).font.bold = True
        ws.cells(current_row, 1).color = (189, 215, 238)
        ws.cells(current_row, 2).color = (189, 215, 238)
        ws.cells(current_row, 3).color = (189, 215, 238)
        current_row += 1

        # Column headers
        for col, label in enumerate(["Strike", "CE LTP", "PE LTP"], start=1):
            ws.cells(current_row, col).value = label
            ws.cells(current_row, col).font.bold = True
            ws.cells(current_row, col).color = (220, 220, 220)
        current_row += 1

        # Strike rows
        for strike in strikes:
            ws.cells(current_row, 1).value = strike

            # Map CE and PE security IDs to their cells
            for _, row in block[block["SEM_STRIKE_PRICE"] == strike].iterrows():
                sid = int(row["SEM_SMST_SECURITY_ID"])
                col = 2 if row["SEM_OPTION_TYPE"] == "CE" else 3
                sid_to_cell[sid] = (current_row, col)

            current_row += 1

        current_row += 1  # blank row between expiry blocks

    return ws, sid_to_cell


# ================= WEBSOCKET FEED =================
def run_feed():
    print("\nSetting up Excel...")
    ws, sid_to_cell = setup_excel()
    print("Excel ready.")

    print("Connecting to Dhan market feed...")
    feed = marketfeed.DhanFeed(CLIENT_ID, ACCESS_TOKEN, instruments, version="v2")
    feed.run_forever()
    print("WebSocket connected. Streaming live premiums...\n")

    while True:
        data = feed.get_data()
        if data:
            security_id = data.get("security_id")
            ltp = data.get("LTP") or data.get("last_price")
            if security_id and ltp:
                sid = int(float(security_id))
                name = sid_to_name.get(sid, str(sid))
                print(f"  {name:40s}  LTP: {ltp}")

                cell = sid_to_cell.get(sid)
                if cell:
                    row, col = cell
                    ws.cells(row, col).value = float(ltp)
                    ws["B2"].value = datetime.now().strftime("%H:%M:%S")


# ================= ENTRY POINT =================
if __name__ == "__main__":
    try:
        run_feed()
    except KeyboardInterrupt:
        print("\nStopped by user.")
