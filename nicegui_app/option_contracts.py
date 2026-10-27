"""
option_contracts.py — which NIFTY / BANKNIFTY options the live options engine trades.

For each index, one CE and one PE (config.OPTIONS_SELECTION):
- Expiry (pick_expiry): today's expiry never counts; then `expiry_skip` more are passed over
  (1 = next-to-next: on 27 Oct NIFTY trades 09 Nov, not 03 Nov), unless that one is more than
  max_days_to_expiry away (BANKNIFTY only has monthly expiries): then the furthest one inside it.
- Strike (pick_strike): of the strikes within strikes_each_side of the ATM, those near the money
  (|delta| in [min_delta, max_delta]), liquid (open interest and today's volume over the minimums, a
  two-sided quote with a spread under max_spread_pct of the premium) and with one lot affordable
  within the per-trade cap. The one with |delta| closest to 0.5 wins (ties: the tighter spread).
- Lot size: from Dhan's NSE_FNO instrument list, read once a day (brokerage.LOT_SIZES if that fails).
"""

import csv
import io
import json
import os
import urllib.request
from datetime import date

import pandas as pd

from brokerage import DEFAULT_LOT_SIZE, LOT_SIZES
from config import INDICES, OPTIONS_SELECTION, OPTIONS_UNDERLYINGS, now_ist

_INSTRUMENTS_URL = "https://api.dhan.co/v2/instrument/NSE_FNO"  # redirects to a ~15 MB CSV
_LOTS_FILE = os.path.join(os.path.dirname(__file__), ".lot_sizes.json")
_lots: dict = {"day": None, "map": {}}


def contract_name(underlying: str, expiry: str, strike: float, opt_type: str) -> str:
    """'NIFTY 09NOV 22700 CE'."""
    return f"{underlying} {pd.Timestamp(expiry):%d%b} {int(strike)} {opt_type}".upper()


def pick_expiry(expiries: list[str], today: date, cfg: dict = OPTIONS_SELECTION) -> str:
    """The expiry to trade from Dhan's list ("YYYY-MM-DD")."""
    future = sorted(e for e in expiries if date.fromisoformat(e) > today)
    if not future:
        raise RuntimeError("no expiry after today")
    i = min(int(cfg["expiry_skip"]), len(future) - 1)
    while i > 0 and (date.fromisoformat(future[i]) - today).days > cfg["max_days_to_expiry"]:
        i -= 1
    return future[i]


def pick_strike(raw: dict, underlying: str, expiry: str, opt_type: str, lot_size: int, max_cost: float,
                cfg: dict = OPTIONS_SELECTION) -> tuple[dict | None, str]:
    """(contract, "") or (None, why none passed) from a Dhan option chain (fetch_option_chain_raw)."""
    step = INDICES[underlying]["strike_step"]
    spot = float(raw["last_price"])
    atm = round(spot / step) * step
    passed, seen = [], 0
    fails = {"delta": 0, "oi": 0, "volume": 0, "spread": 0, "cost": 0}
    for k, sides in (raw.get("oc") or {}).items():
        strike = float(k)
        if abs(strike - atm) > cfg["strikes_each_side"] * step + 1e-6:
            continue
        q = sides.get(opt_type.lower()) or {}
        ltp = float(q.get("last_price") or 0)
        if not q.get("security_id") or ltp <= 0:
            continue
        seen += 1
        bid, ask = float(q.get("top_bid_price") or 0), float(q.get("top_ask_price") or 0)
        c = {
            "symbol": contract_name(underlying, expiry, strike, opt_type), "underlying": underlying,
            "opt_type": opt_type, "expiry": expiry, "strike": strike, "security_id": str(q["security_id"]),
            "lot_size": int(lot_size), "premium": ltp, "spot": spot, "atm": atm,
            "delta": abs(float((q.get("greeks") or {}).get("delta") or 0)),
            "iv": float(q.get("implied_volatility") or 0),
            "oi": int(q.get("oi") or 0), "volume": int(q.get("volume") or 0),
            "spread_pct": (ask - bid) / ltp * 100 if bid > 0 and ask >= bid else float("inf"),
        }
        bad = [name for name, ok in (
            ("delta", cfg["min_delta"] <= c["delta"] <= cfg["max_delta"]),
            ("oi", c["oi"] >= cfg["min_oi"]),
            ("volume", c["volume"] >= cfg["min_volume"]),
            ("spread", c["spread_pct"] <= cfg["max_spread_pct"]),
            ("cost", ltp * lot_size <= max_cost),
        ) if not ok]
        for name in bad:
            fails[name] += 1
        if not bad:
            passed.append(c)
    if passed:
        return min(passed, key=lambda c: (abs(c["delta"] - 0.5), c["spread_pct"])), ""
    if not seen:
        return None, f"no {opt_type} quotes near the {atm:,.0f} ATM"
    why = {"delta": f"|delta| outside {cfg['min_delta']}–{cfg['max_delta']}",
           "oi": f"OI under {cfg['min_oi']:,}", "volume": f"volume under {cfg['min_volume']:,}",
           "spread": f"spread over {cfg['max_spread_pct']}%", "cost": f"a lot costs over ₹{max_cost:,.0f}"}
    return None, (f"none of {seen} {opt_type} strikes near the {atm:,.0f} ATM passes: "
                  + ", ".join(f"{n} {why[k]}" for k, n in fails.items() if n))


def needs_reselect(c: dict | None, spot: float | None, today: str, cfg: dict = OPTIONS_SELECTION) -> bool:
    """No contract yet, chosen on another day, or the index has moved reselect_strikes from its ATM."""
    if c is None or c.get("chosen_on") != today:
        return True
    if spot is None:
        return False
    step = INDICES[c["underlying"]]["strike_step"]
    return abs(spot - c["atm"]) >= cfg["reselect_strikes"] * step


# ── lot sizes ─────────────────────────────────────────────────────────────────

def _download_lots() -> dict[str, int]:
    """{"NIFTY|2026-11-09": 65, …} for every NIFTY / BANKNIFTY option expiry in Dhan's list."""
    with urllib.request.urlopen(_INSTRUMENTS_URL, timeout=60) as resp:
        text = io.TextIOWrapper(resp, encoding="utf-8", newline="")
        lots = {}
        for row in csv.DictReader(text):
            if row.get("INSTRUMENT") == "OPTIDX" and row.get("UNDERLYING_SYMBOL") in OPTIONS_UNDERLYINGS:
                lots[f"{row['UNDERLYING_SYMBOL']}|{row['SM_EXPIRY_DATE']}"] = int(float(row["LOT_SIZE"]))
    return lots


def lot_size(underlying: str, expiry: str) -> int:
    """Units per lot for this index and expiry: Dhan's instrument list (downloaded once a day, kept in
    .lot_sizes.json across restarts), else brokerage.LOT_SIZES."""
    today = now_ist().date().isoformat()
    if _lots["day"] != today:
        lots = {}
        try:
            with open(_LOTS_FILE) as f:
                saved = json.load(f)
            if saved.get("day") == today:
                lots = saved["lots"]
        except (FileNotFoundError, json.JSONDecodeError, KeyError):
            pass
        if not lots:
            try:
                lots = _download_lots()
                with open(_LOTS_FILE, "w") as f:
                    json.dump({"day": today, "lots": lots}, f)
            except Exception as e:
                print(f"  [options] lot sizes from Dhan failed ({e}), using brokerage.LOT_SIZES")
        _lots.update(day=today, map=lots)
    return _lots["map"].get(f"{underlying}|{expiry}") or LOT_SIZES.get(underlying, DEFAULT_LOT_SIZE)
