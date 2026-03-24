"""
nifty_option_chain.py
---------------------
Fetches NIFTY CE & PE LTPs via Dhan REST API option_chain endpoint.
Displays in Excel and auto-refreshes every REFRESH_SECONDS.
"""

import os
import time
from datetime import datetime, date
from dotenv import load_dotenv
from dhanhq import dhanhq
import xlwings as xw

# ================= CONFIG =================
STRIKE_RANGE    = 500   # ATM ± points to show
REFRESH_SECONDS = 30

# ================= ENV =================
ENV_FILE = os.path.join(os.path.dirname(__file__), "..", ".env")
load_dotenv(dotenv_path=ENV_FILE, override=True)

CLIENT_ID    = os.getenv("DHAN_CLIENT_CODE")
ACCESS_TOKEN = os.getenv("DHAN_TOKEN_ID")
dhan = dhanhq(CLIENT_ID, ACCESS_TOKEN)

# ================= NIFTY identifiers =================
NIFTY_SCRIP   = 13        # Dhan security_id for NIFTY 50
NIFTY_SEGMENT = "IDX_I"   # exchange segment for index


def get_expiries(count=3):
    """Return the nearest `count` future expiry date strings (YYYY-MM-DD)."""
    r = dhan.expiry_list(NIFTY_SCRIP, NIFTY_SEGMENT)
    if r.get("status") != "success":
        raise RuntimeError(f"expiry_list failed: {r}")

    data = r["data"]
    if isinstance(data, dict):
        data = data.get("data", data)
    if isinstance(data, dict):
        data = next(iter(data.values()))

    today = date.today()
    expiries = sorted(
        d for d in data
        if isinstance(d, str) and datetime.strptime(d, "%Y-%m-%d").date() > today
    )
    if not expiries:
        raise RuntimeError("No future expiries found.")
    return expiries[:count]


def fetch_option_chain(expiry):
    """Fetch option chain, return (spot_price, list of row dicts)."""
    r = dhan.option_chain(NIFTY_SCRIP, NIFTY_SEGMENT, expiry)
    if r.get("status") != "success":
        raise RuntimeError(f"option_chain failed: {r}")

    inner = r["data"]["data"]
    spot = float(inner["last_price"])
    oc = inner["oc"]

    rows = []
    for strike_str, sides in oc.items():
        strike = float(strike_str)
        for opt_type, key in [("CE", "ce"), ("PE", "pe")]:
            info = sides.get(key, {})
            if not info:
                continue
            greeks = info.get("greeks", {})
            rows.append({
                "strike":   strike,
                "type":     opt_type,
                "ltp":      float(info.get("last_price", 0)),
                "oi":       int(info.get("oi", 0)),
                "iv":       float(info.get("implied_volatility", 0)),
                "volume":   int(info.get("volume", 0)),
                "delta":    float(greeks.get("delta", 0)),
                "gamma":    float(greeks.get("gamma", 0)),
                "theta":    float(greeks.get("theta", 0)),
                "vega":     float(greeks.get("vega", 0)),
            })
    return spot, rows


def write_to_excel(ws, spot, atm, expiry, rows, refreshed_at):
    """Write option chain data to Excel sheet."""
    ws.clear()

    # Title
    ws["A1"].value = (
        f"NIFTY Option Chain  |  Spot: {spot}  |  ATM: {atm}  "
        f"|  Expiry: {expiry}  |  Refreshed: {refreshed_at}"
    )
    ws["A1"].font.bold = True
    ws["A1"].font.size = 12

    # Filter strikes around ATM
    lower = atm - STRIKE_RANGE
    upper = atm + STRIKE_RANGE

    # Filter and build flat list: CE then PE per strike, grouped by strike
    exp_date = datetime.strptime(expiry, "%Y-%m-%d")
    exp_tag = exp_date.strftime("%d%b").upper()  # e.g. "30MAR"

    strike_rows = {}
    for r in rows:
        if r["strike"] < lower or r["strike"] > upper:
            continue
        strike_rows.setdefault(r["strike"], {})[r["type"]] = r

    strikes = sorted(strike_rows.keys())

    # Headers
    headers = ["Name", "LTP", "OI", "IV", "Volume", "Delta", "Gamma", "Theta", "Vega"]
    for col, h in enumerate(headers, start=1):
        cell = ws.cells(3, col)
        cell.value = h
        cell.font.bold = True
        cell.color = (180, 198, 231)

    num_cols = len(headers)

    # Data rows — all CEs first, then all PEs
    row_num = 4
    for opt_type in ["CE", "PE"]:
        # Section header
        ws.cells(row_num, 1).value = f"— {opt_type} —"
        ws.cells(row_num, 1).font.bold = True
        row_num += 1

        for strike in strikes:
            info = strike_rows[strike].get(opt_type, {})
            name = f"NIFTY {exp_tag} {int(strike)} {opt_type}"
            ws.cells(row_num, 1).value = name
            ws.cells(row_num, 2).value = info.get("ltp", "")
            ws.cells(row_num, 3).value = info.get("oi", "")
            iv = info.get("iv", "")
            ws.cells(row_num, 4).value = f"{iv}%" if iv != "" else ""
            ws.cells(row_num, 5).value = info.get("volume", "")
            ws.cells(row_num, 6).value = info.get("delta", "")
            ws.cells(row_num, 7).value = info.get("gamma", "")
            ws.cells(row_num, 8).value = info.get("theta", "")
            ws.cells(row_num, 9).value = info.get("vega", "")
            if strike == atm:
                for c in range(1, num_cols + 1):
                    ws.cells(row_num, c).color = (255, 255, 153)
            row_num += 1

        row_num += 1  # blank row between CE and PE

    # Column widths
    for col, w in zip("ABCDEFGHI", [24, 10, 12, 8, 10, 8, 8, 8, 8]):
        ws.range(f"{col}:{col}").column_width = w

    print(f"  Written {len(strikes)} strikes to Excel")


def main():
    print("Fetching expiries...")
    expiries = get_expiries(3)
    print(f"Expiries: {expiries}")

    print("Setting up Excel...")
    app = xw.App(visible=True)
    wb = app.books.add()

    # Create one sheet per expiry
    sheets = {}
    for i, expiry in enumerate(expiries):
        if i == 0:
            ws = wb.sheets[0]
        else:
            ws = wb.sheets.add(after=wb.sheets[wb.sheets.count - 1])
        ws.name = f"Expiry {expiry}"
        sheets[expiry] = ws

    while True:
        print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Refreshing...")
        for expiry in expiries:
            try:
                spot, rows = fetch_option_chain(expiry)
                atm = round(spot / 50) * 50
                print(f"  [{expiry}] Spot: {spot}  ATM: {atm}")
                write_to_excel(sheets[expiry], spot, atm, expiry, rows, datetime.now().strftime("%H:%M:%S"))
            except Exception as e:
                print(f"  [{expiry}] [error] {e}")

        time.sleep(REFRESH_SECONDS)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped by user.")
