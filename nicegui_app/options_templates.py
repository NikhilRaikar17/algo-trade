"""
Options strategy templates, paper-traded: the opt_* templates switched on for Options P&L on the
Strategies page (long call, bull call spread, bull put spread, long straddle, iron condor), on NIFTY and
BANKNIFTY, in the options paper account (account.OPTIONS) next to the options engine's single-leg trades.
Rules in config.OPTIONS_TEMPLATES.

- Entry: at most once a day per template and index, when its rule fires on the index's 15-min bars
  (entry_trigger). The legs are whole strike steps from the ATM at the options engine's expiry, priced
  at their last traded premium from the option chain (build_legs); a leg without a two-sided quote, or
  with a spread over OPTIONS_TEMPLATE_MAX_SPREAD_PCT, means no entry.
- Booking: one position priced at its net premium (plan): a debit (long call, spreads bought, straddle)
  is a BUY of its value, a credit (bull put spread, iron condor) a SELL of the cost to close it. The
  account sizes it in whole lots to the max loss at its stop and takes or skips it like any signal; a
  credit position ties up its max loss at expiry (the spread width less the credit) as capital, and each
  leg is charged as its own pair of orders (account.legs_charges).
- Exit: monitor_tick() prices each open position from its legs' live ticks and closes it at its target
  or stop; the options engine's square-off closes the rest at OPTIONS_LIMITS["square_off"].

Nothing here places an order. run_tick() and monitor_tick() run inside options_engine's loops.
"""

import threading
import time
from datetime import datetime, timedelta

import pandas as pd
from dhanhq import marketfeed

import live_candles
import ws_feed
from account import OPTIONS, size_text
from config import (INDICES, OPTIONS_TEMPLATE_MAX_SPREAD_PCT, OPTIONS_TEMPLATES, OPTIONS_UNDERLYINGS, now_ist)
from data import fetch_index_15min_candles, fetch_option_chain_raw, get_expiries
from option_contracts import contract_name, lot_size, pick_expiry
from state import _send_telegram
from strategy_registry import get_options_pnl_strategy_keys, get_strategy_rows
from trade_desk import TAKEN, _hhmm

BAR = timedelta(minutes=15)
_CHAIN_GAP_SECONDS = 3  # Dhan allows one option-chain call every 3 s

_lock = threading.Lock()
_status: dict[tuple[str, str], str] = {}  # (index, template key) → what it is waiting for, or what happened


# ── rules (pure) ──────────────────────────────────────────────────────────────

def finished_bars(bars: pd.DataFrame, now: datetime) -> pd.DataFrame:
    """Today's 15-min bars that have closed by `now`."""
    if bars.empty:
        return bars
    day = bars[bars["timestamp"].dt.date == now.date()]
    return day[day["timestamp"] + BAR <= pd.Timestamp(now)].reset_index(drop=True)


def entry_trigger(cfg: dict, bars: pd.DataFrame) -> tuple[pd.Timestamp | None, str]:
    """(the bar the entry rule fired on, "") or (None, what it is waiting for), from today's finished
    15-min bars; the first is the opening range."""
    if bars.empty:
        return None, "waiting for the opening range (09:15–09:30)"
    first, last = bars.iloc[0], bars.iloc[-1]
    hi, lo = float(first["high"]), float(first["low"])
    kind = cfg["entry"]
    if kind == "breakout":
        if len(bars) > 1 and float(last["close"]) > hi:
            return last["timestamp"], ""
        return None, f"waiting for a 15-min close above the opening range high {hi:,.2f}"
    if kind == "squeeze":
        pct = (hi - lo) / float(first["open"]) * 100
        if pct <= cfg["max_range_pct"]:
            return first["timestamp"], ""
        return None, f"opening range {pct:.2f}% is over {cfg['max_range_pct']}%: no squeeze today"
    if kind == "range":
        pct = (float(bars["high"].max()) - float(bars["low"].min())) / float(first["open"]) * 100
        close = float(last["close"])
        if pct > cfg["max_range_pct"]:
            return None, f"today's range {pct:.2f}% is over {cfg['max_range_pct']}%"
        if not lo <= close <= hi:
            return None, f"waiting for a close back inside the opening range {lo:,.2f}–{hi:,.2f}"
        return last["timestamp"], ""
    raise ValueError(f"unknown entry rule {kind!r}")


def build_legs(raw: dict, underlying: str, expiry: str, legs_cfg: list) -> tuple[list[dict] | None, str]:
    """The template's legs from a Dhan option chain (fetch_option_chain_raw): each at its strike steps
    from the ATM, priced at its last traded premium. → (legs, "") or (None, why not)."""
    step = INDICES[underlying]["strike_step"]
    spot = float(raw["last_price"])
    atm = round(spot / step) * step
    chain = {float(k): v for k, v in (raw.get("oc") or {}).items()}
    legs = []
    for opt_type, steps, qty in legs_cfg:
        strike = float(atm + steps * step)
        q = (chain.get(strike) or {}).get(opt_type.lower()) or {}
        ltp = float(q.get("last_price") or 0)
        bid, ask = float(q.get("top_bid_price") or 0), float(q.get("top_ask_price") or 0)
        name = contract_name(underlying, expiry, strike, opt_type)
        if not q.get("security_id") or ltp <= 0:
            return None, f"no quote for {name}"
        if bid <= 0 or ask < bid:
            return None, f"{name} has no two-sided quote"
        spread = (ask - bid) / ltp * 100
        if spread > OPTIONS_TEMPLATE_MAX_SPREAD_PCT:
            return None, f"{name} spread {spread:.1f}% is over {OPTIONS_TEMPLATE_MAX_SPREAD_PCT}%"
        legs.append({"symbol": name, "opt_type": opt_type, "strike": strike, "qty": int(qty),
                     "security_id": str(q["security_id"]), "premium": round(ltp, 2)})
    return legs, ""


def expiry_value(legs: list[dict], spot: float) -> float:
    """Σ qty × intrinsic value of the legs with the index at `spot` (per unit)."""
    return sum(leg["qty"] * (max(spot - leg["strike"], 0.0) if leg["opt_type"] == "CE"
                             else max(leg["strike"] - spot, 0.0)) for leg in legs)


def position_value(legs: list[dict], prices: list[float], side: str) -> float:
    """The position's price: a debit's value (BUY), or a credit's cost to close (SELL)."""
    net = sum(leg["qty"] * p for leg, p in zip(legs, prices))
    return round(net if side == "BUY" else -net, 2)


def plan(legs: list[dict], cfg: dict) -> dict:
    """Side, entry, target, stop and capital per unit of the position, from its legs' premiums.
    Raises ValueError when it cannot be traded as configured."""
    net = sum(leg["qty"] * leg["premium"] for leg in legs)
    strikes = sorted(leg["strike"] for leg in legs)
    grid = [0.0, *strikes, strikes[-1] * 2]
    values = [expiry_value(legs, s) for s in grid]
    tp, sl = cfg["target_pct"] / 100, cfg["stop_pct"] / 100
    if net > 0:  # debit: bought for its value
        entry, target, stop = net, net * (1 + tp), net * (1 - sl)
        bounded = expiry_value(legs, strikes[-1] * 10) <= values[-1] + 1e-9
        if bounded:
            target = min(target, max(values) * 0.95)
        if target <= entry:
            raise ValueError(f"the most it can be worth ({max(values):,.2f}) leaves no room over its "
                             f"{entry:,.2f} cost")
        return {"side": "BUY", "entry": round(entry, 2), "target": round(target, 2), "stop_loss": round(stop, 2),
                "cost_per_unit": round(entry, 2)}
    credit = -net
    if credit <= 0:
        raise ValueError("the legs net to no premium")
    if expiry_value(legs, strikes[-1] * 10) < values[-1] - 1e-9:
        raise ValueError("an unhedged short call: the loss has no limit")
    width = -min(values)  # the most it can cost to close at expiry
    stop = min(credit * (1 + sl), width * 0.95)
    if width <= credit or stop <= credit:
        raise ValueError(f"the {credit:,.2f} credit leaves no room under the {width:,.2f} spread width")
    return {"side": "SELL", "entry": round(credit, 2), "target": round(credit * (1 - tp), 2),
            "stop_loss": round(stop, 2), "cost_per_unit": round(width - credit, 2)}


def position_symbol(underlying: str, expiry: str, name: str, legs: list[dict]) -> str:
    """'NIFTY 09NOV IRON CONDOR 24600P/24700P/25300C/25400C'."""
    strikes = "/".join(f"{int(leg['strike'])}{leg['opt_type'][0]}" for leg in legs)
    return f"{underlying} {pd.Timestamp(expiry):%d%b} {name} {strikes}".upper()


def legs_text(legs: list[dict]) -> str:
    return " · ".join(f"{'BUY' if leg['qty'] > 0 else 'SELL'} {leg['symbol']} @ {leg['premium']:,.2f}"
                      for leg in legs)


# ── the loop ──────────────────────────────────────────────────────────────────

def _names() -> dict[str, str]:
    """Template key → the strategy name its trades are booked under ("Options · Iron Condor")."""
    return {r["key"]: r["short_name"] for r in get_strategy_rows() if r["key"] in OPTIONS_TEMPLATES}


def _decided_today(now: datetime) -> dict[tuple[str, str], dict]:
    """(index, strategy name) → today's book entry for it, if the account has decided one."""
    return {(r.get("underlying"), r["strategy"]): r for r in OPTIONS.decisions(now.strftime("%Y-%m-%d")).values()
            if r.get("legs")}


def _set_status(underlying: str, key: str, text: str) -> None:
    with _lock:
        _status[(underlying, key)] = text


def _enter(underlying: str, key: str, name: str, cfg: dict, fired: pd.Timestamp, now: datetime) -> None:
    """The rule fired: build the legs and let the account take or skip the position."""
    idx = INDICES[underlying]
    expiry = pick_expiry(get_expiries(idx["scrip"], idx["segment"], count=12), now.date())
    time.sleep(_CHAIN_GAP_SECONDS)
    raw = fetch_option_chain_raw(idx["scrip"], idx["segment"], expiry)
    legs, why = build_legs(raw, underlying, expiry, cfg["legs"])
    if legs is None:
        _set_status(underlying, key, f"rule fired at {fired + BAR:%H:%M}, not entered: {why}")
        return
    try:
        p = plan(legs, cfg)
    except ValueError as e:
        _set_status(underlying, key, f"rule fired at {fired + BAR:%H:%M}, not entered: {e}")
        return
    symbol = position_symbol(underlying, expiry, name.split("·")[-1].strip(), legs)
    OPTIONS.meta[symbol] = {"underlying": underlying, "expiry": expiry, "lot_size": lot_size(underlying, expiry),
                            "group": f"{underlying} {name}", "legs": legs, "template": key,
                            "cost_per_unit": p["cost_per_unit"]}
    trade = {"time": fired.isoformat(), "entry": p["entry"], "stop_loss": p["stop_loss"], "target": p["target"],
             "signal": f"{p['side']} {legs_text(legs)}"}
    rec, new = OPTIONS.open_signal(trade, name, symbol, p["entry"], now)
    if not rec or not new:
        return
    _set_status(underlying, key, f"entered {now:%H:%M} · {symbol}" if rec["verdict"] == TAKEN
                else f"skipped {now:%H:%M}: {'; '.join(rec['reasons'])}")
    head =(f"[{name}] | {symbol}\n{legs_text(legs)}\nNet {'debit' if p['side'] == 'BUY' else 'credit'} "
            f"₹{p['entry']:,.2f} · target {p['target']:,.2f} · stop {p['stop_loss']:,.2f}")
    if rec["verdict"] == TAKEN:
        _send_telegram(f"{OPTIONS.tag}NEW TRADE {head}\nSize: {size_text(rec)} · capital ₹{rec['capital']:,.0f}"
                       + "".join(f"\nNote: {w}" for w in rec["warnings"]))
    else:
        _send_telegram(f"{OPTIONS.tag}SKIPPED {head}\nNot taken: " + "; ".join(rec["reasons"]))


def run_tick(now: datetime | None = None) -> None:
    """At a bar close: for each enabled template and index not yet decided today, check its entry rule
    and enter when it fires."""
    now = now or now_ist()
    keys = [k for k in get_options_pnl_strategy_keys() if k in OPTIONS_TEMPLATES]
    with _lock:
        for k in list(_status):
            if k[1] not in keys:
                del _status[k]
    if not keys:
        return
    names, decided = _names(), _decided_today(now)
    for u in OPTIONS_UNDERLYINGS:
        bars = None
        for key in keys:
            cfg, name = OPTIONS_TEMPLATES[key], names.get(key, key)
            done = decided.get((u, name))
            if done:
                what = (f"entered {done['decided_at'][11:16]} · {done['symbol']}" if done["verdict"] == TAKEN
                        else f"skipped {done['decided_at'][11:16]}: {'; '.join(done['reasons'])}")
                _set_status(u, key, what)
                continue
            start, end = (_hhmm(t) for t in cfg["window"])
            if now.time() < start:
                _set_status(u, key, f"entry window opens at {cfg['window'][0]}")
                continue
            if now.time() > end:
                _set_status(u, key, f"no entry today (window closed at {cfg['window'][1]})")
                continue
            if bars is None:
                bars = finished_bars(fetch_index_15min_candles(u), now)
            fired, why = entry_trigger(cfg, bars)
            if fired is None:
                _set_status(u, key, why)
                continue
            try:
                _enter(u, key, name, cfg, fired, now)
            except Exception as e:
                _set_status(u, key, f"rule fired, entry failed: {e}")
                print(f"  [templates] {u} {key}: entry failed: {e}")


def _leg_key(leg: dict) -> str:
    return ws_feed.feed_key(marketfeed.NSE_FNO, leg["security_id"])


def monitor_tick(max_age: float) -> None:
    """Live leg premiums for the open positions: close each at its target or stop on the first tick there."""
    trades = [r for r in OPTIONS.open_trades() if r.get("legs")]
    ws_feed.watch("option_templates", [(marketfeed.NSE_FNO, leg["security_id"]) for r in trades for leg in r["legs"]])
    for r in trades:
        prices = [live_candles.last_price(_leg_key(leg), max_age=max_age) for leg in r["legs"]]
        if any(p is None for p in prices):
            continue
        rec = OPTIONS.on_tick(r["key"], position_value(r["legs"], prices, r["side"]), legs_last=prices)
        if rec:
            print(f"  [templates] {rec['symbol']} {rec['status']} at {rec['exit_price']:.2f}")
            _send_telegram(OPTIONS.closed_text(rec))
            OPTIONS.alert_day_stop()


def snapshot() -> list[dict]:
    """For Live P&L Options: per index and enabled template, what it is waiting for or what it did."""
    names = _names()
    with _lock:
        return [{"underlying": u, "key": k, "name": names.get(k, k), "status": s}
                for (u, k), s in sorted(_status.items(), key=lambda kv: (kv[0][0], list(OPTIONS_TEMPLATES).index(kv[0][1])))]
