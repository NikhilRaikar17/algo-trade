"""
The live paper accounts: starting funds from a fixed start moment, compounded with every closed
trade's net P&L, i.e. after brokerage, STT, exchange, GST, SEBI and stamp charges.

- EQUITY: the stocks the live engine trades (config.RISK_LIMITS, .live_account.json / .live_book.json).
- OPTIONS: NIFTY / BANKNIFTY options the options engine buys (config.OPTIONS_LIMITS,
  .live_account_options.json / .live_book_options.json), sized in whole lots, charged as F&O.

Each account's book holds one decision per live signal, made once, the first time the engine sees the
signal (open_signal): trade_desk.check() sizes it to risk the max loss at the stop and takes or skips it
against the account at that moment. A taken trade holds its capital until it hits its target or stop
(on_tick / close_signal) or is squared off at limits["square_off"] (square_off). Decisions are never
worked out again, so nothing changes after the fact. Only taken trades are alerted on Telegram and count
in the balance. Nothing here places an order.

The start moment and starting funds live in the settings file (created on first use, "now"), so the
balance survives restarts; reset_account() starts a fresh account (the book's older entries are kept
but no longer counted).

The module-level functions (open_signal, account_state, …) are the EQUITY account's.
"""

import json
import os
import threading
from datetime import datetime

import pandas as pd

from backtest_metrics import _CHARGE_KEYS, inr, rupees_text
from brokerage import calculate_brokerage
from config import IST, OPTIONS_LIMITS, RISK_LIMITS, now_ist
from trade_desk import SKIPPED, TAKEN, Book, _hhmm, check, day_stop, signal_key, to_row

_DIR = os.path.dirname(__file__)


def qty_text(r: dict) -> str:
    """'10' shares, or '2 lots (130)' of an option."""
    lot = int(r.get("lot_size") or 1)
    if lot == 1:
        return f"{r['qty']:,}"
    lots = r["qty"] // lot
    return f"{lots} lot{'s' if lots != 1 else ''} ({r['qty']:,})"


def size_text(r: dict) -> str:
    """'BUY 10 × ₹2,303.70 = ₹23,037 · risks ₹230 at the stop' for alerts."""
    return (f"{r['side']} {qty_text(r)} × ₹{r['entry']:,.2f} = ₹{inr(r['capital'])} · "
            f"risks ₹{inr(r['max_loss'])} at the stop")


def pnl_text(r: dict) -> str:
    what = "shares" if int(r.get("lot_size") or 1) == 1 else "units"
    return f"{rupees_text(r['net'])} net on {r['qty']:,} {what} (after ₹{inr(r['charges'])} charges)"


def _ts(s):
    return pd.Timestamp(s).tz_convert(IST) if s else None


def _is_open(r: dict) -> bool:
    return r["verdict"] == TAKEN and r["status"] == "Open"


def _plan(trade: dict) -> dict:
    """The signal without the engine's running price fields."""
    return {k: v for k, v in trade.items() if k not in ("unrealized_pnl", "exit_price")}


def _record(row, trade: dict, now: datetime, status: str | None) -> dict:
    return {
        "key": row.key, "strategy": row.strategy, "symbol": row.symbol, "signal": str(trade.get("signal", "")),
        "side": row.side, "time": pd.Timestamp(row.signal_time).isoformat(),
        "decided_at": now.isoformat(timespec="seconds"), "trade_date": now.strftime("%Y-%m-%d"),
        "entry": row.entry, "stop_loss": row.stop, "target": row.target,
        "verdict": row.verdict, "reasons": row.reasons, "warnings": row.warnings,
        "qty": row.qty, "lot_size": row.lot_size, "capital": row.capital, "max_loss": row.max_loss,
        "risk_per_share": row.risk_per_share, "reward_risk": row.reward_risk,
        "status": status, "last_price": row.current_price,
        "exit_price": None, "exit_time": None, "gross": 0.0, "charges": 0.0, "net": 0.0,
    }


def _level(r: dict, status: str) -> float:
    """Where a bracket order fills: at the target or at the stop."""
    return float(r["target"] if status == "Target Hit" else r["stop_loss"])


class PaperAccount:
    """One paper account and its book. `tag` prefixes its Telegram alerts; `history` saves its
    signals to .trade_history.json (the stock signals the Strategy Analysis judges); `meta` holds
    extra fields per symbol (an option's security id, lot size, …) copied into new book entries."""

    def __init__(self, name: str, settings_file: str, book_file: str, limits: dict,
                 tag: str = "", history: bool = True):
        self.name, self.file, self.book_file, self.limits = name, settings_file, book_file, limits
        self.tag, self.history = tag, history
        self.meta: dict[str, dict] = {}
        self._lock = threading.RLock()  # the engine thread and the pages both read and write the book

    @property
    def segment(self) -> str:
        return self.limits.get("segment", "equity_intraday")

    # ── settings ──────────────────────────────────────────────────────────────

    def get_settings(self) -> dict:
        """{"start": ISO datetime, "initial": ₹}. Creates the account (starting now) on first use."""
        try:
            with open(self.file, "r") as f:
                s = json.load(f)
            if s.get("start") and s.get("initial"):
                return s
        except (FileNotFoundError, json.JSONDecodeError):
            pass
        return self.reset_account()

    def reset_account(self, initial: float | None = None) -> dict:
        """Start a fresh account now with `initial` ₹ (default limits["funds"])."""
        s = {"start": now_ist().isoformat(timespec="seconds"), "initial": float(initial or self.limits["funds"])}
        with open(self.file, "w") as f:
            json.dump(s, f)
        return s

    def start_time(self) -> datetime:
        ts = pd.Timestamp(self.get_settings()["start"])
        return ts.tz_localize(IST) if ts.tzinfo is None else ts

    def in_account(self, trades: list[dict]) -> list[dict]:
        """Signals that closed after the account started (normalized trades: exit_time is a Timestamp).
        For judging strategies on every signal; the account's own trades come from account_state()."""
        start = self.start_time()
        return [t for t in trades if t["exit_time"] >= start]

    # ── the book ──────────────────────────────────────────────────────────────

    def _load_book(self) -> dict:
        try:
            with open(self.book_file, "r") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def _save_book(self, book: dict) -> None:
        tmp = self.book_file + ".tmp"
        with open(tmp, "w") as f:
            json.dump(book, f)
        os.replace(tmp, self.book_file)

    def _counted(self, book: dict) -> list[dict]:
        """Book entries made since the account started, oldest first."""
        start = self.start_time()
        recs = [r for r in book.values() if _ts(r["decided_at"]) >= start]
        return sorted(recs, key=lambda r: r["decided_at"])

    def _pnl(self, r: dict, exit_price: float) -> dict:
        b = calculate_brokerage(r["entry"], exit_price, lot_size=1, quantity=r["qty"],
                                segment=self.segment, short=r["side"] == "SELL")
        return {"gross": b["gross_pnl"], "charges": b["total_charges"], "net": b["net_pnl"],
                "charge_parts": {k: b[k] for k in _CHARGE_KEYS}}

    def _holdings(self, recs: list[dict], today: str) -> Book:
        initial = float(self.get_settings()["initial"])
        open_ = [r for r in recs if _is_open(r)]
        taken_today = [r for r in recs if r["verdict"] == TAKEN and r["trade_date"] == today]
        return Book(
            balance=initial + sum(r["net"] for r in recs if r["verdict"] == TAKEN and r["status"] != "Open"),
            open_capital=sum(r["capital"] for r in open_),
            open_symbols={r["symbol"] for r in open_} | {r["group"] for r in open_ if r.get("group")},
            taken_today=len(taken_today),
            day_stopped=day_stop([r for r in taken_today if r["status"] != "Open"], self.limits),
        )

    def day_status(self, now: datetime | None = None) -> tuple[float, str]:
        """(today's net P&L of closed trades, why trading is over for today or "")."""
        today = (now or now_ist()).strftime("%Y-%m-%d")
        with self._lock:
            recs = self._counted(self._load_book())
        closed = [r for r in recs if r["verdict"] == TAKEN and r["trade_date"] == today and r["status"] != "Open"]
        return sum(r["net"] for r in closed), day_stop(closed, self.limits)

    def open_signal(self, trade: dict, strategy: str, symbol: str, price: float,
                    now: datetime | None = None) -> tuple[dict | None, bool]:
        """Take or skip a signal the engine sees open at `price`. → (book entry, decided just now).
        The decision is made once; later calls only return it."""
        now = now or now_ist()
        key = signal_key(trade, strategy, symbol)
        if key is None:
            return None, False
        with self._lock:
            book = self._load_book()
            if key in book:
                return book[key], False
            row = to_row(_plan(trade), strategy, symbol)
            if row is None:
                return None, False
            meta = self.meta.get(symbol, {})
            row.current_price, row.lot_size, row.group = price, int(meta.get("lot_size") or 1), meta.get("group", "")
            check(row, self._holdings(self._counted(book), now.strftime("%Y-%m-%d")), self.limits, now)
            book[key] = rec = {**meta, **_record(row, trade, now, "Open" if row.verdict == TAKEN else None)}
            self._save_book(book)
        return rec, True

    def mark_price(self, trade: dict, strategy: str, symbol: str, price: float) -> None:
        """Latest price of an open taken trade, for unrealised P&L and the square-off."""
        key = signal_key(trade, strategy, symbol)
        with self._lock:
            book = self._load_book()
            r = book.get(key)
            if r and _is_open(r) and r["last_price"] != price:
                r["last_price"] = price
                self._save_book(book)

    def _close(self, r: dict, exit_price: float, status: str, now: datetime) -> None:
        r.update(status=status, exit_price=float(exit_price), last_price=float(exit_price),
                 exit_time=now.isoformat(timespec="seconds"), **self._pnl(r, float(exit_price)))

    def on_tick(self, key: str, price: float, now: datetime | None = None) -> dict | None:
        """A live price for an open taken trade: closes it at the target or stop the moment the price
        reaches it (→ the book entry), else records the price (→ None)."""
        now = now or now_ist()
        with self._lock:
            book = self._load_book()
            r = book.get(key)
            if not r or not _is_open(r):
                return None
            buy = r["side"] == "BUY"
            status = ("Target Hit" if (price >= r["target"] if buy else price <= r["target"])
                      else "SL Hit" if (price <= r["stop_loss"] if buy else price >= r["stop_loss"]) else None)
            if status:
                self._close(r, _level(r, status), status, now)
            elif r["last_price"] == price:
                return None
            else:
                r["last_price"] = price
            self._save_book(book)
        return r if status else None

    def open_trades(self) -> list[dict]:
        """Open taken trades counted in the account."""
        with self._lock:
            return [r for r in self._counted(self._load_book()) if _is_open(r)]

    def close_signal(self, trade: dict, strategy: str, symbol: str, exit_price: float, status: str,
                     now: datetime | None = None) -> dict | None:
        """The engine's candle check found the signal past its target or stop (the live-tick monitor,
        on_tick, usually gets there first). Fills at the target or stop level, as a bracket order would.
        → its book entry if this closed a taken trade, else None. A signal never seen open (already past
        its target or stop at first sight) is booked as skipped."""
        now = now or now_ist()
        key = signal_key(trade, strategy, symbol)
        if key is None:
            return None
        with self._lock:
            book = self._load_book()
            r = book.get(key)
            if r is None:
                row = to_row(_plan(trade), strategy, symbol)
                if row is None:
                    return None
                row.verdict, row.reasons = SKIPPED, ["hit its target or stop before the engine saw it open"]
                book[key] = {**self.meta.get(symbol, {}), **_record(row, trade, now, None)}
                self._save_book(book)
                return None
            if not _is_open(r):
                return None
            self._close(r, _level(r, status), status, now)
            self._save_book(book)
        return r

    def square_off(self, now: datetime | None = None) -> list[dict]:
        """Close every open taken trade at its last price once it is limits["square_off"], or if it was
        left open on an earlier day (the app was down), and Telegram each one. → the trades closed."""
        from state import _send_telegram  # noqa: PLC0415 — state pulls in the Dhan client; keep imports light

        now = now or now_ist()
        today, late = now.strftime("%Y-%m-%d"), now.time() >= _hhmm(self.limits["square_off"])
        closed = []
        with self._lock:
            book = self._load_book()
            for r in book.values():
                if _is_open(r) and (late or r["trade_date"] < today):
                    self._close(r, r["last_price"] or r["entry"], "Day Close", now)
                    closed.append(r)
            if closed:
                self._save_book(book)
        for r in closed:
            _send_telegram(f"{self.tag}SQUARED OFF [{r['strategy']}] | {r['symbol']}\n{r['side']} {qty_text(r)} @ "
                           f"{r['entry']:,.2f} → {r['exit_price']:,.2f} at {self.limits['square_off']}\n"
                           f"PnL: {pnl_text(r)}")
        return closed

    def closed_text(self, r: dict) -> str:
        """TRADE CLOSED alert for a taken trade."""
        return (f"{self.tag}TRADE CLOSED [{r['strategy']}] | {r['symbol']}\n{r['side']} {qty_text(r)} @ "
                f"{r['entry']:,.2f} → {r['exit_price']:,.2f}\nPnL: {pnl_text(r)}\nStatus: {r['status']}")

    def alert_day_stop(self, now: datetime | None = None) -> None:
        """Telegram once when today's trading stops (losing streak or daily loss)."""
        from state import _is_already_sent, _mark_sent, _send_telegram  # noqa: PLC0415

        now = now or now_ist()
        day_net, stopped = self.day_status(now)
        key = f"{self.tag.strip().lower()}{'_' if self.tag else ''}day_stopped_{now:%Y-%m-%d}"
        if stopped and not _is_already_sent(key):
            _mark_sent(key)
            _send_telegram(f"{self.tag}TRADING STOPPED FOR TODAY\n{stopped}\nToday's P&L: {rupees_text(day_net)} net"
                           "\nNo new trades until tomorrow; open trades run to their target, stop or square-off.")

    def decisions(self, day: str | None = None) -> dict:
        """{signal key: book entry} decided on `day` (default today)."""
        day = day or now_ist().strftime("%Y-%m-%d")
        with self._lock:
            return {k: r for k, r in self._load_book().items() if r["trade_date"] == day}

    # ── account state ─────────────────────────────────────────────────────────

    def account_state(self, now: datetime | None = None) -> dict:
        """Balance, funds and trades from the book.

        Returns initial, start, balance (initial + realized net), realized (net), gross, charges, trades,
        wins, losses, return_pct, in_positions (capital of open trades), free, unrealized (before charges),
        open, sized (closed taken trades, P&L-widget shape), positions (open taken book entries, with
        "unrealized"), skipped_today (today's skipped book entries)."""
        from backtest_metrics import summarize  # noqa: PLC0415

        now = now or now_ist()
        self.square_off(now)
        with self._lock:
            recs = self._counted(self._load_book())
        initial = float(self.get_settings()["initial"])
        sized = [_as_trade(r) for r in recs if r["verdict"] == TAKEN and r["status"] != "Open"]
        s = summarize(sized)
        positions = []
        for r in recs:
            if _is_open(r):
                price = float(r["last_price"] or r["entry"])
                move = (price - r["entry"]) if r["side"] == "BUY" else (r["entry"] - price)
                positions.append({**r, "stock": r["symbol"], "time": _ts(r["time"]), "unrealized": move * r["qty"]})
        balance = initial + s["net"]
        in_positions = sum(p["capital"] for p in positions)
        today = now.strftime("%Y-%m-%d")
        return {
            "initial": initial, "start": self.start_time(), "balance": balance,
            "realized": s["net"], "gross": s["gross"], "charges": s["charges"],
            "trades": s["trades"], "wins": s["wins"], "losses": s["losses"],
            "return_pct": (balance - initial) / initial * 100,
            "in_positions": in_positions, "free": max(balance - in_positions, 0.0),
            "unrealized": sum(p["unrealized"] for p in positions), "open": len(positions),
            "sized": sized, "positions": positions,
            "skipped_today": [{**r, "stock": r["symbol"]} for r in recs
                              if r["verdict"] == SKIPPED and r["trade_date"] == today],
        }

    def current_state(self) -> dict:
        return self.account_state()


def _as_trade(r: dict) -> dict:
    """A closed taken trade in the shape size_trades() gives the P&L widgets."""
    entry, exit_px = float(r["entry"]), float(r["exit_price"])
    return {
        **r, "stock": r["symbol"], "time": _ts(r["time"]), "exit_time": _ts(r["exit_time"]),
        "pnl": (exit_px - entry) if r["side"] == "BUY" else (entry - exit_px),
        "funds_cut": any("size cut" in w for w in r["warnings"]),
        "ret_pct": r["net"] / r["capital"] * 100 if r["capital"] else 0.0,
    }


EQUITY = PaperAccount("Stocks", os.path.join(_DIR, ".live_account.json"), os.path.join(_DIR, ".live_book.json"),
                      RISK_LIMITS)
OPTIONS = PaperAccount("Options", os.path.join(_DIR, ".live_account_options.json"),
                       os.path.join(_DIR, ".live_book_options.json"), OPTIONS_LIMITS, tag="OPTIONS ", history=False)

# the stock account's functions, as before
get_settings, reset_account, start_time, in_account = (
    EQUITY.get_settings, EQUITY.reset_account, EQUITY.start_time, EQUITY.in_account)
day_status, open_signal, mark_price, on_tick = EQUITY.day_status, EQUITY.open_signal, EQUITY.mark_price, EQUITY.on_tick
open_trades, close_signal, square_off = EQUITY.open_trades, EQUITY.close_signal, EQUITY.square_off
closed_text, alert_day_stop, decisions = EQUITY.closed_text, EQUITY.alert_day_stop, EQUITY.decisions
account_state, current_state = EQUITY.account_state, EQUITY.current_state
