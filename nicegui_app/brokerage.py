"""
Dhan brokerage and taxes calculator for F&O (options) trades.

Reference: https://dhan.co/charges/
Charges apply per executed order (buy + sell = 2 orders per round trip).

  Brokerage:          ₹20 flat per order (or 0.03% of turnover, whichever is lower)
  STT:                0.0625% of premium on SELL side
  Exchange charges:   0.035% of turnover (NSE F&O)
  GST:                18% on (brokerage + exchange charges)
  SEBI charges:       ₹10 per crore of turnover (≈ negligible for small lots)
  Stamp duty:         0.003% of premium on BUY side

All amounts in ₹.
"""

# ---------- constants ----------------------------------------------------------------

_BROKERAGE_FLAT = 20.0          # ₹ per order
_BROKERAGE_PCT  = 0.0003        # 0.03 % (fallback if flat is higher — take lower)
_STT_PCT        = 0.000625      # 0.0625 % on sell-side premium
_EXCHANGE_PCT   = 0.00035       # 0.035 % NSE F&O transaction charge
_GST_PCT        = 0.18          # 18 % on (brokerage + exchange charges)
_SEBI_PER_CRORE = 10.0          # ₹10 per crore of turnover
_STAMP_PCT      = 0.00003       # 0.003 % on buy-side premium

# Standard lot sizes (current as of 2025-26 revision)
LOT_SIZES: dict[str, int] = {
    "NIFTY":     75,
    "BANKNIFTY": 35,
    "SENSEX":    10,
    "FINNIFTY":  65,
    "MIDCPNIFTY": 75,
}
DEFAULT_LOT_SIZE = 75  # fallback


def get_lot_size(instrument: str) -> int:
    """Return the lot size for a known index, or DEFAULT_LOT_SIZE."""
    return LOT_SIZES.get(instrument.upper(), DEFAULT_LOT_SIZE)


# ---------- core calculation ---------------------------------------------------------

def calculate_brokerage(
    entry_price: float,
    exit_price: float,
    lot_size: int = DEFAULT_LOT_SIZE,
    quantity: int = 1,          # number of lots
) -> dict:
    """
    Return a breakdown dict with all charges for one round-trip (buy + sell) trade.

    Parameters
    ----------
    entry_price : float   option premium at entry (₹ per unit)
    exit_price  : float   option premium at exit  (₹ per unit)
    lot_size    : int     units per lot (e.g. 75 for NIFTY)
    quantity    : int     number of lots traded

    Returns
    -------
    dict with keys:
        gross_pnl      – (exit - entry) × lot_size × quantity
        brokerage      – ₹ charged by Dhan (both legs)
        stt            – Securities Transaction Tax (sell leg)
        exchange       – NSE exchange transaction charge
        gst            – GST on brokerage + exchange
        sebi           – SEBI turnover fee
        stamp          – Stamp duty (buy leg)
        total_charges  – sum of all charges
        net_pnl        – gross_pnl − total_charges
    """
    units = lot_size * quantity
    buy_turnover  = entry_price * units
    sell_turnover = exit_price  * units

    # Brokerage: ₹20 flat or 0.03 % of turnover, whichever is lower — per order
    brokerage_buy  = min(_BROKERAGE_FLAT, _BROKERAGE_PCT * buy_turnover)
    brokerage_sell = min(_BROKERAGE_FLAT, _BROKERAGE_PCT * sell_turnover)
    brokerage = brokerage_buy + brokerage_sell

    # STT — only on sell side for options
    stt = _STT_PCT * sell_turnover

    # Exchange transaction charge (both sides)
    exchange = _EXCHANGE_PCT * (buy_turnover + sell_turnover)

    # GST on brokerage + exchange charges
    gst = _GST_PCT * (brokerage + exchange)

    # SEBI charges (₹10 per crore)
    total_turnover = buy_turnover + sell_turnover
    sebi = _SEBI_PER_CRORE * total_turnover / 1_00_00_000  # per crore

    # Stamp duty — on buy side only
    stamp = _STAMP_PCT * buy_turnover

    total_charges = brokerage + stt + exchange + gst + sebi + stamp
    gross_pnl = (exit_price - entry_price) * units
    net_pnl = gross_pnl - total_charges

    return {
        "gross_pnl":     round(gross_pnl, 2),
        "brokerage":     round(brokerage, 2),
        "stt":           round(stt, 4),
        "exchange":      round(exchange, 4),
        "gst":           round(gst, 4),
        "sebi":          round(sebi, 4),
        "stamp":         round(stamp, 4),
        "total_charges": round(total_charges, 2),
        "net_pnl":       round(net_pnl, 2),
    }


def charges_for_trades(
    trades: list[dict],
    lot_size: int = DEFAULT_LOT_SIZE,
    quantity: int = 1,
) -> dict:
    """
    Aggregate brokerage breakdown across a list of completed trades.
    Each trade must have 'entry' and 'exit_price' keys.

    Returns the same keys as calculate_brokerage() but summed, plus:
        per_trade_avg_charges  – average total charges per trade
    """
    totals = {
        "gross_pnl": 0.0,
        "brokerage": 0.0,
        "stt": 0.0,
        "exchange": 0.0,
        "gst": 0.0,
        "sebi": 0.0,
        "stamp": 0.0,
        "total_charges": 0.0,
        "net_pnl": 0.0,
    }
    n = 0
    for t in trades:
        entry = float(t.get("entry", 0) or 0)
        exit_px = float(t.get("exit_price", 0) or 0)
        if entry <= 0 or exit_px <= 0:
            # Fall back to raw pnl if prices are missing
            totals["gross_pnl"] += float(t.get("pnl", 0))
            totals["net_pnl"]   += float(t.get("pnl", 0))
            continue
        b = calculate_brokerage(entry, exit_px, lot_size, quantity)
        for k in totals:
            totals[k] += b[k]
        n += 1

    totals = {k: round(v, 2) for k, v in totals.items()}
    totals["per_trade_avg_charges"] = round(totals["total_charges"] / n, 2) if n else 0.0
    return totals
