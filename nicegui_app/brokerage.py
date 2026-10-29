"""
Dhan brokerage and taxes calculator.

Supports four segments:
  - "equity_intraday"  — NSE equity intraday (MIS)
  - "equity_delivery"  — NSE equity delivery (CNC)
  - "fno"              — NSE F&O (options)
  - "fno_futures"      — NSE index futures, the long-term account

Reference: https://dhan.co/charges/

All amounts in ₹.
"""

# ---------- constants ----------------------------------------------------------------

_BROKERAGE_FLAT = 20.0          # ₹ per executed order (Dhan flat fee; F&O always pays it)
_BROKERAGE_PCT  = 0.0003        # 0.03% — equity intraday pays whichever of the two is lower
_GST_PCT        = 0.18          # 18% on (brokerage + exchange charges + SEBI fees + IPFT)
_SEBI_PER_CRORE = 10.0          # ₹10 per crore of turnover
_IPFT_PCT       = 0.000000001   # 0.0000001% of turnover (IPFT contribution), shown under exchange

# Equity intraday (MIS) rates — dhan.co/pricing, checked 2026-10-27
_EQ_STT_PCT        = 0.00025      # 0.025% on sell-side turnover
_EQ_EXCHANGE_PCT   = 0.000030699  # 0.0030699% NSE transaction charge, as Dhan lists it
_EQ_STAMP_PCT      = 0.00003      # 0.003% on buy-side turnover

# Equity delivery (CNC) rates — no brokerage at Dhan; the DP charge is paid on the sell day
_DEL_STT_PCT       = 0.001        # 0.1% on buy and sell turnover
_DEL_STAMP_PCT     = 0.00015      # 0.015% on buy-side turnover
_DEL_DP_CHARGE     = 12.5         # ₹ per scrip sold (CDSL + Dhan), GST on top

# Index futures rates (on the contract value, not the margin)
_FUT_STT_PCT       = 0.0005     # 0.05% on sell-side turnover (Finance Act 2026, from 1 Apr 2026)
_FUT_EXCHANGE_PCT  = 0.0000173  # 0.00173% NSE futures transaction charge
_FUT_STAMP_PCT     = 0.00002    # 0.002% on buy-side turnover

# F&O (options) rates
_FNO_STT_PCT       = 0.0015     # 0.15% on sell-side premium (Finance Act 2026, from 1 Apr 2026)
_FNO_EXCHANGE_PCT  = 0.0003503  # 0.03503% NSE options transaction charge on premium
_FNO_STAMP_PCT     = 0.00003    # 0.003% on buy-side premium

# NSE lot sizes from Dhan's NSE_FNO instrument list (api.dhan.co/v2/instrument/NSE_FNO), 2026-10-27.
# The live options engine reads them from that list each day (option_contracts.lot_size); these are
# the fallback.
LOT_SIZES: dict[str, int] = {
    "NIFTY":      65,
    "BANKNIFTY":  30,
    "FINNIFTY":   60,
    "MIDCPNIFTY": 120,
}
DEFAULT_LOT_SIZE = 65  # fallback


def get_lot_size(instrument: str) -> int:
    """Return the lot size for a known index, or DEFAULT_LOT_SIZE."""
    return LOT_SIZES.get(instrument.upper(), DEFAULT_LOT_SIZE)


# ---------- core calculation ---------------------------------------------------------

def _rupee(x: float) -> float:
    """Nearest rupee, halves up (Dhan rounds STT and stamp duty this way)."""
    return float(int(x + 0.5))


def calculate_brokerage(
    entry_price: float,
    exit_price: float,
    lot_size: int = DEFAULT_LOT_SIZE,
    quantity: int = 1,
    segment: str = "fno",        # "fno" | "fno_futures" | "equity_intraday" | "equity_delivery"
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
    segment     : str     "fno", "fno_futures", "equity_intraday" or "equity_delivery"

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
    elif segment == "equity_delivery":
        stt_pct      = _DEL_STT_PCT
        exchange_pct = _EQ_EXCHANGE_PCT
        stamp_pct    = _DEL_STAMP_PCT
    elif segment == "fno_futures":
        stt_pct      = _FUT_STT_PCT
        exchange_pct = _FUT_EXCHANGE_PCT
        stamp_pct    = _FUT_STAMP_PCT
    else:  # fno
        stt_pct      = _FNO_STT_PCT
        exchange_pct = _FNO_EXCHANGE_PCT
        stamp_pct    = _FNO_STAMP_PCT

    units = lot_size * quantity
    buy_price, sell_price = (exit_price, entry_price) if short else (entry_price, exit_price)
    buy_turnover  = buy_price  * units
    sell_turnover = sell_price * units

    # Brokerage per order: equity intraday ₹20 or 0.03% of turnover, whichever is lower; F&O flat ₹20
    if segment == "equity_intraday":
        brokerage_buy  = min(_BROKERAGE_FLAT, _BROKERAGE_PCT * buy_turnover)
        brokerage_sell = min(_BROKERAGE_FLAT, _BROKERAGE_PCT * sell_turnover)
    elif segment == "equity_delivery":
        brokerage_buy, brokerage_sell = 0.0, _DEL_DP_CHARGE  # shown under brokerage, so GST applies to it
    else:
        brokerage_buy = brokerage_sell = _BROKERAGE_FLAT
    brokerage = brokerage_buy + brokerage_sell

    # STT — sell side only (delivery: both sides), rounded to the rupee as on the contract note
    stt = _rupee(stt_pct * (buy_turnover + sell_turnover if segment == "equity_delivery" else sell_turnover))

    # Exchange transaction charge + IPFT (both sides)
    total_turnover = buy_turnover + sell_turnover
    exchange = (exchange_pct + _IPFT_PCT) * total_turnover

    # SEBI charges (₹10 per crore)
    sebi = _SEBI_PER_CRORE * total_turnover / 1_00_00_000

    # GST on brokerage + exchange (incl. IPFT) + SEBI charges
    gst = _GST_PCT * (brokerage + exchange + sebi)

    # Stamp duty — on buy side only, rounded to the rupee
    stamp = _rupee(stamp_pct * buy_turnover)

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
