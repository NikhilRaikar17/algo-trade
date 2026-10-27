"""
Live options engine: NIFTY and BANKNIFTY options, bought on signals from their own premium charts, in
the options paper account (account.OPTIONS). The same feed-driven loop as the stock engine
(trading_engine.py), independent of any browser connection:

- Contracts: at each 5-minute bar close, a CE and a PE per index, chosen by option_contracts
  (next-to-next expiry, near the money, liquid, a lot within the per-trade cap). The choice holds for
  the day and is made again only when the index moves OPTIONS_SELECTION["reselect_strikes"] strikes
  from it; a contract with an open trade keeps being run until that trade closes.
- Candles: each contract's ticks (NSE_FNO on the websocket) build 5-minute bars (live_candles), seeded
  once from REST for the bars before it was subscribed.
- Signals: the enabled live strategies on each contract's chart, at the live premium. Only BUY signals
  are traded — options are bought, never written (a SELL on the CE chart shows up as a BUY on the PE's).
  One position per index at a time ("NIFTY options"), same risk rules as the stock account.
- Exits: run_options_monitor() closes an open trade at its target or stop on the first tick there;
  the square-off closes the rest at RISK_LIMITS["square_off"].
"""

import asyncio
import threading
import time
import traceback

from dhanhq import marketfeed

import live_candles
import ws_feed
from account import OPTIONS
from config import INDICES, OPTIONS_LIMITS, OPTIONS_UNDERLYINGS, now_ist
from data import fetch_option_candles, fetch_option_chain_raw, get_expiries
from option_contracts import lot_size, needs_reselect, pick_expiry, pick_strike
from state import _send_telegram, get_live_price, is_market_open
from strategy_registry import get_live_strategy_keys
from trading_engine import _STRATEGY_RUNNERS, _TICK_MAX_AGE, MONITOR_SECONDS, _seconds_to_next_bar, detect_signals

OPT_TYPES = ("CE", "PE")
_CHAIN_GAP_SECONDS = 3  # Dhan allows one option-chain call every 3 s

_lock = threading.Lock()
_chosen: dict[tuple[str, str], dict] = {}   # (index, "CE"/"PE") → the contract being traded
_status: dict[str, str] = {}                # index → why it has no contract, or the last selection error
_store: dict[str, dict] = {}                # contract symbol → {strategy key: {"active", "completed"}}


def _key(security_id: str) -> str:
    return ws_feed.feed_key(marketfeed.NSE_FNO, security_id)


def _meta(c: dict) -> dict:
    """What the book keeps with a trade in this contract (and the monitor needs to price it)."""
    return {"security_id": c["security_id"], "underlying": c["underlying"], "opt_type": c["opt_type"],
            "expiry": c["expiry"], "strike": c["strike"], "lot_size": c["lot_size"],
            "group": f"{c['underlying']} options"}


def _select(underlying: str, now) -> None:
    """Choose today's CE and PE for one index from its option chain."""
    cfg = INDICES[underlying]
    expiry = pick_expiry(get_expiries(cfg["scrip"], cfg["segment"], count=12), now.date())
    raw = fetch_option_chain_raw(cfg["scrip"], cfg["segment"], expiry)
    lot = lot_size(underlying, expiry)
    balance = OPTIONS.account_state(now)["balance"]
    max_cost = balance * float(OPTIONS_LIMITS.get("max_capital_pct") or 100) / 100
    why = []
    for t in OPT_TYPES:
        c, reason = pick_strike(raw, underlying, expiry, t, lot, max_cost)
        old = _chosen.get((underlying, t))
        if c is None:
            why.append(reason)
            if old and old.get("chosen_on") != now.strftime("%Y-%m-%d"):
                with _lock:
                    _chosen.pop((underlying, t), None)   # yesterday's pick: nothing to trade today
            continue
        c.update(chosen_on=now.strftime("%Y-%m-%d"), chosen_at=now.strftime("%H:%M"))
        with _lock:
            _chosen[(underlying, t)] = c
        if not old or old["symbol"] != c["symbol"]:
            print(f"  [options] {underlying} {t}: {c['symbol']} @ {c['premium']:.2f} "
                  f"(delta {c['delta']:.2f}, OI {c['oi']:,}, spread {c['spread_pct']:.2f}%)")
    _status[underlying] = "; ".join(why)


def _contracts_to_run() -> list[dict]:
    """The chosen contracts, plus any contract with an open trade (until it closes)."""
    with _lock:
        out = {c["symbol"]: c for c in _chosen.values()}
    for r in OPTIONS.open_trades():
        if r.get("security_id") and r["symbol"] not in out:
            out[r["symbol"]] = {"symbol": r["symbol"], **_meta(r)}
    return list(out.values())


def option_candles(c: dict):
    """Today's finished 5-minute bars of a contract from the feed, seeded from REST first if needed."""
    key = _key(c["security_id"])
    if live_candles.needs_seed(key):
        rest = fetch_option_candles(c["security_id"])
        time.sleep(0.35)  # back-to-back REST calls get rate-limited
        live_candles.seed(key, rest)
    return live_candles.candles(key)


def _run_contract(c: dict, live_keys: list[str]) -> None:
    candles = option_candles(c)
    if candles.empty:
        print(f"  [options] {c['symbol']}: no candles yet today")
        return
    live = live_candles.last_price(_key(c["security_id"]))
    price = round(live if live is not None else float(candles["close"].iloc[-1]), 2)
    full = live_candles.candles(_key(c["security_id"]), history=True)
    results = {}
    for k in live_keys:
        _, classify = _STRATEGY_RUNNERS[k]
        try:
            buys = [s for s in detect_signals(k, candles, full) if float(s["target"]) > float(s["entry"])]
            active, completed = classify(buys, price, c["symbol"], book=OPTIONS)
            results[k] = {"active": active, "completed": completed}
        except Exception:
            print(f"  [options:{k}:{c['symbol']}] {traceback.format_exc()}")
    with _lock:
        _store[c["symbol"]] = results
    print(f"  [options] {c['symbol']} @ {price:.2f} ({'feed' if live is not None else 'last bar'}) "
          f"— {len(candles)} bars, strategies updated")


def _run_options_tick(now=None) -> None:
    """At a bar close: (re)choose contracts where needed, put them on the feed, run the strategies."""
    now = now or now_ist()
    today = now.strftime("%Y-%m-%d")
    first = True
    for u in OPTIONS_UNDERLYINGS:
        spot = (get_live_price(u) or {}).get("ltp")
        if any(needs_reselect(_chosen.get((u, t)), spot, today) for t in OPT_TYPES):
            if not first:
                time.sleep(_CHAIN_GAP_SECONDS)
            first = False
            try:
                _select(u, now)
            except Exception as e:
                _status[u] = f"could not choose contracts: {e}"
                print(f"  [options] {u}: {_status[u]}")

    contracts = _contracts_to_run()
    for c in contracts:
        OPTIONS.meta[c["symbol"]] = _meta(c)
    ws_feed.watch("options", [(marketfeed.NSE_FNO, c["security_id"]) for c in contracts])
    live_keys = get_live_strategy_keys()
    for c in contracts:
        try:
            _run_contract(c, live_keys)
        except Exception as e:
            print(f"  [options:{c['symbol']}] candles/classify failed: {e}")
    with _lock:
        for sym in set(_store) - {c["symbol"] for c in contracts}:
            del _store[sym]

    for r in OPTIONS.square_off():
        print(f"  [options] squared off {r['symbol']} ({r['strategy']}) at {r['exit_price']:.2f}")


def _options_monitor_tick() -> None:
    """Live premiums for the open option trades: close each at its target or stop on the first tick there."""
    trades = [r for r in OPTIONS.open_trades() if r.get("security_id")]
    ws_feed.watch("options_positions", [(marketfeed.NSE_FNO, r["security_id"]) for r in trades])
    for r in trades:
        ltp = live_candles.last_price(_key(r["security_id"]), max_age=_TICK_MAX_AGE)
        if ltp is None:
            continue
        rec = OPTIONS.on_tick(r["key"], ltp)
        if rec:
            print(f"  [options monitor] {rec['symbol']} {rec['status']} at {rec['exit_price']:.2f} (tick {ltp:.2f})")
            _send_telegram(OPTIONS.closed_text(rec))
            OPTIONS.alert_day_stop()


def snapshot() -> dict:
    """For the Live P&L Options page: the contracts being traded, why an index has none, and today's
    open signals per contract."""
    with _lock:
        signals = {sym: sum(len(v["active"]) for v in res.values()) for sym, res in _store.items()}
        contracts = [dict(_chosen[k]) for k in sorted(_chosen)]
        status = {u: s for u, s in _status.items() if s}
    return {"contracts": contracts, "status": status, "signals": signals}


async def run_options_engine():
    """Async loop: _run_options_tick() once at start-up, then just after every 5-minute bar closes,
    in market hours. Start once from main.py."""
    print("  [options] Options engine started (feed-driven, every 5-minute bar).")
    loop = asyncio.get_event_loop()
    first = True
    while True:
        if not first:
            await asyncio.sleep(_seconds_to_next_bar(now_ist()))
        first = False
        if not is_market_open():
            continue
        try:
            await loop.run_in_executor(None, _run_options_tick)
        except Exception as e:
            print(f"  [options] tick error: {e}\n{traceback.format_exc()}")


async def run_options_monitor():
    """Async loop: _options_monitor_tick() every MONITOR_SECONDS in market hours. Start once from main.py."""
    loop = asyncio.get_event_loop()
    while True:
        await asyncio.sleep(MONITOR_SECONDS)
        if not is_market_open():
            continue
        try:
            await loop.run_in_executor(None, _options_monitor_tick)
        except Exception as e:
            print(f"  [options monitor] error: {e}\n{traceback.format_exc()}")
