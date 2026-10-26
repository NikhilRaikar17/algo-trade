"""
Dhan brokerage and taxes calculator.

Supports two segments:
  - "equity_intraday"  — NSE equity intraday (MIS)
  - "fno"              — NSE F&O (options)

Reference: https://dhan.co/charges/

All amounts in ₹.
"""

# ---------- constants ----------------------------------------------------------------

_BROKERAGE_FLAT = 20.0          # ₹ per order (Dhan flat-fee)
_BROKERAGE_PCT  = 0.0003        # 0.03% — fallback; take whichever is lower
_GST_PCT        = 0.18          # 18% on (brokerage + exchange charges)
_SEBI_PER_CRORE = 10.0          # ₹10 per crore of turnover

# Equity intraday (MIS) rates
_EQ_STT_PCT        = 0.00025    # 0.025% on sell-side turnover
_EQ_EXCHANGE_PCT   = 0.0000297  # 0.00297% NSE equity transaction charge (since Oct 2024)
_EQ_STAMP_PCT      = 0.00003    # 0.003% on buy-side turnover

# F&O (options) rates
_FNO_STT_PCT       = 0.001      # 0.1% on sell-side premium (since Oct 2024)
_FNO_EXCHANGE_PCT  = 0.0003503  # 0.03503% NSE options transaction charge on premium
_FNO_STAMP_PCT     = 0.00003    # 0.003% on buy-side premium

# Standard lot sizes (current as of 2025-26 revision)
LOT_SIZES: dict[str, int] = {
    "NIFTY":      75,
    "BANKNIFTY":  35,
    "SENSEX":     10,
    "FINNIFTY":   65,
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
    quantity: int = 1,
    segment: str = "fno",        # "fno" | "equity_intraday"
    short: bool = False,         # True: sold at entry, bought back at exit
) -> dict:
    """
    Return a breakdown dict with all charges for one round-trip (buy + sell) trade.

    Parameters
    ----------
    entry_price : float   price at entry (₹ per unit)
    exit_price  : float   price at exit  (₹ per unit)
    lot_size    : int     units per lot (1 for equity shares)
    quantity    : int     number of lots / shares traded
    segment     : str     "fno" or "equity_intraday"

    Returns
    -------
    dict with keys:
        gross_pnl      – (exit - entry) × lot_size × quantity; (entry - exit) × … when short
        brokerage      – ₹ charged by Dhan (both legs)
        stt            – Securities Transaction Tax (sell leg)
        exchange       – NSE exchange transaction charge
        gst            – GST on brokerage + exchange
        sebi           – SEBI turnover fee
        stamp          – Stamp duty (buy leg)
        total_charges  – sum of all charges
        net_pnl        – gross_pnl − total_charges
    """
    if segment == "equity_intraday":
        stt_pct      = _EQ_STT_PCT
        exchange_pct = _EQ_EXCHANGE_PCT
        stamp_pct    = _EQ_STAMP_PCT
    else:  # fno
        stt_pct      = _FNO_STT_PCT
        exchange_pct = _FNO_EXCHANGE_PCT
        stamp_pct    = _FNO_STAMP_PCT

    units = lot_size * quantity
    buy_price, sell_price = (exit_price, entry_price) if short else (entry_price, exit_price)
    buy_turnover  = buy_price  * units
    sell_turnover = sell_price * units

    # Brokerage: ₹20 flat or 0.03% of turnover, whichever is lower — per order
    brokerage_buy  = min(_BROKERAGE_FLAT, _BROKERAGE_PCT * buy_turnover)
    brokerage_sell = min(_BROKERAGE_FLAT, _BROKERAGE_PCT * sell_turnover)
    brokerage = brokerage_buy + brokerage_sell

    # STT — only on sell side
    stt = stt_pct * sell_turnover

    # Exchange transaction charge (both sides)
    exchange = exchange_pct * (buy_turnover + sell_turnover)

    # SEBI charges (₹10 per crore)
    total_turnover = buy_turnover + sell_turnover
    sebi = _SEBI_PER_CRORE * total_turnover / 1_00_00_000

    # GST on brokerage + exchange + SEBI charges
    gst = _GST_PCT * (brokerage + exchange + sebi)

    # Stamp duty — on buy side only
    stamp = stamp_pct * buy_turnover

    total_charges = brokerage + stt + exchange + gst + sebi + stamp
    gross_pnl = (sell_price - buy_price) * units
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


def is_short(trade: dict) -> bool:
    """Sold first? Decided by the target (below the entry), else the signal text ("SELL …"),
    else the P&L sign vs the price move."""
    entry = float(trade.get("entry") or 0)
    target = trade.get("target")
    if target is not None and entry:
        return float(target) < entry
    signal = str(trade.get("signal") or "").strip().upper()
    if signal.startswith(("SELL", "BUY")):
        return signal.startswith("SELL")
    exit_px = float(trade.get("exit_price") or 0)
    pnl = float(trade.get("pnl") or 0)
    return bool(entry and exit_px and pnl and (exit_px - entry) * pnl < 0)


def charges_for_trades(
    trades: list[dict],
    lot_size: int = DEFAULT_LOT_SIZE,
    quantity: int = 1,
    segment: str = "fno",
) -> dict:
    """
    Aggregate brokerage breakdown across a list of completed trades.
    Each trade must have 'entry' and 'exit_price' keys; a trade whose target is below its entry
    is treated as a short.

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
            raw = float(t.get("pnl", 0)) * quantity
            totals["gross_pnl"] += raw
            totals["net_pnl"]   += raw
            continue
        b = calculate_brokerage(entry, exit_px, lot_size, quantity, segment, short=is_short(t))
        for k in totals:
            totals[k] += b[k]
        n += 1

    totals = {k: round(v, 2) for k, v in totals.items()}
    totals["per_trade_avg_charges"] = round(totals["total_charges"] / n, 2) if n else 0.0
    return totals
