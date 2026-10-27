"""
Daily LIVE report + strategy analysis email. Live results only; the backtest P&L is the separate
4 PM BACKTEST email (email_report.py), so a day's backtest total appears in one place.

Sent once per trading day from 15:45 IST, after the close (retried until 20:00 if a build fails or the
app restarts mid-build; marked sent only once it has gone out). The live report part is the
two paper accounts — stocks (account.EQUITY) and NIFTY / BANKNIFTY options (account.OPTIONS) — and
today's live trades in each, trade by trade; the analysis part answers "what went right, what went
wrong, which strategies work" from:

  * today's live trades in both accounts (compounding, after brokerage and taxes),
  * the Strategy Analysis verdicts (strategy_review.py): last 7 days of backtest + live since the
    account started, judged on the share of trades that lose money after charges (shown as rates,
    not ₹ — the backtest's ₹ P&L is in the BACKTEST email).

gather() does the I/O; insights() and build_html() are pure, so the email can be built and checked
without sending anything.
"""

import threading
from collections import defaultdict
from html import escape

from account import qty_text
from backtest_metrics import inr, rupees_text, sizing_label, summarize
from config import STRATEGY_REVIEW, _is_trading_day, now_ist
from state import _is_already_sent, _mark_sent
from strategy_review import GOOD, NOT_GOOD, TOO_EARLY, WATCH, build_reviews

SEND_WINDOW = ((15, 45), (20, 0))   # from after the 15:30 close; later minutes are retries
MAX_ATTEMPTS = 3                    # builds per day (each backtests every top stock)
_CHARGES_HEAVY = 0.30               # flag a day when charges eat more than 30% of the gross profit

_GREEN, _RED, _AMBER, _GREY, _INK = "#1e8449", "#c0392b", "#b9770e", "#7f8c8d", "#2c3e50"
_VERDICT_COLOR = {NOT_GOOD: _RED, WATCH: _AMBER, GOOD: _GREEN, TOO_EARLY: _GREY}


# ── data ──────────────────────────────────────────────────────────────────────

def gather(now) -> dict:
    """Backtests for every strategy, the live account and its trades. Slow (one candle fetch per
    top stock): run it in a worker thread."""
    from account import OPTIONS, account_state, in_account              # noqa: PLC0415
    from db import get_active_top_stocks                                  # noqa: PLC0415
    from live_trades import load_live_trades                              # noqa: PLC0415
    from pages.backtest_pnl_tab import _fetch_all_stocks_trades          # noqa: PLC0415
    from strategy_registry import get_strategy_rows                       # noqa: PLC0415

    rows = get_strategy_rows()
    report: dict = {}
    backtest = _fetch_all_stocks_trades(get_active_top_stocks(), report, keys=[r["key"] for r in rows])
    completed, _, _ = load_live_trades()
    return {
        "now": now, "rows": rows, "backtest": backtest, "backtest_report": report,
        "live": in_account(completed), "account": account_state(now), "options": OPTIONS.account_state(now),
    }


def _made_lost(v: float) -> str:
    """'made ₹1,165' / 'lost ₹704' — the verb carries the sign."""
    return f"{'made' if v >= 0 else 'lost'} ₹{inr(v)}"


def _by_strategy(sized: list[dict], key: str = "strategy") -> dict[str, list]:
    groups = defaultdict(list)
    for t in sized:
        groups[t.get(key)].append(t)
    return groups


def insights(data: dict) -> dict:
    """Everything the email shows, worked out from gather()'s output."""
    today = data["now"].strftime("%Y-%m-%d")
    acct, opts = data["account"], data["options"]
    live_on = {r["key"] for r in data["rows"] if r["live_enabled"]}

    # today, live: each account's own trades (they shared its funds, as they really would)
    live_today = [t for t in acct["sized"] if t["trade_date"] == today]
    opt_today = [t for t in opts["sized"] if t["trade_date"] == today]
    live_rows = {name: summarize(ts) for name, ts in _by_strategy(live_today).items()}
    opt_rows = {name: summarize(ts) for name, ts in _by_strategy(opt_today).items()}

    reviews = build_reviews(data["backtest"], data["live"], data["rows"], float(acct["initial"]))

    right, wrong = [], []
    if not live_today and not opt_today:
        wrong.append("No live trades closed today, so neither paper account moved.")
    for where, rows in (("stocks", live_rows), ("options", opt_rows)):
        for name, s in sorted(rows.items(), key=lambda kv: -kv[1]["net"]):
            line = f"{name} {_made_lost(s['net'])} on {where} today ({s['wins']}W/{s['losses']}L)"
            (right if s["net"] > 0 else wrong).append(line)

    every_today = live_today + opt_today
    if every_today:
        best = max(every_today, key=lambda t: t["net"])
        worst = min(every_today, key=lambda t: t["net"])
        if best["net"] > 0:
            right.append(f"Best trade: {best.get('stock', '?')} {best['side']} ({best['strategy']}) "
                         f"{rupees_text(best['net'])}")
        if worst["net"] < 0:
            wrong.append(f"Worst trade: {worst.get('stock', '?')} {worst['side']} ({worst['strategy']}) "
                         f"{rupees_text(worst['net'])}")
        day = summarize(every_today)
        if day["gross"] > 0 and day["charges"] > _CHARGES_HEAVY * day["gross"]:
            wrong.append(f"Charges took ₹{inr(day['charges'])} of ₹{inr(day['gross'])} gross profit "
                         f"({day['charges'] / day['gross'] * 100:.0f}%) — small moves barely cover brokerage and taxes.")

    for r in reviews:
        if r.verdict == GOOD:
            right.append(f"{r.name} passes the review: " + "; ".join(r.reasons))
        elif r.verdict == NOT_GOOD:
            act = " It is still switched on for Live — consider turning it off." if r.key in live_on else ""
            wrong.append(f"{r.name} is Not good: " + "; ".join(r.reasons) + "." + act)
        elif r.verdict == WATCH:
            wrong.append(f"{r.name} needs watching: " + "; ".join(r.reasons))

    return {
        "today": today, "account": acct, "options": opts, "live_today": live_today, "opt_today": opt_today,
        "live_rows": live_rows, "opt_rows": opt_rows, "reviews": reviews, "right": right, "wrong": wrong,
        "live_on": live_on,
    }


# ── HTML (inline styles: email clients ignore <style>) ────────────────────────

def _money(v: float) -> str:
    color = _GREEN if v > 0 else _RED if v < 0 else _INK
    return f'<span style="color:{color};font-weight:bold;">{rupees_text(v)}</span>'


_TH = "padding:6px 10px;background:#1b2631;color:#fff;font-size:12px;text-align:left;"
_TD = "padding:6px 10px;border-bottom:1px solid #e5e8e8;font-size:13px;"


def _table(head: list[str], rows: list[list[str]]) -> str:
    th = "".join(f'<th style="{_TH}">{h}</th>' for h in head)
    body = "".join("<tr>" + "".join(f'<td style="{_TD}">{c}</td>' for c in r) + "</tr>" for r in rows)
    return f'<table style="border-collapse:collapse;margin:8px 0 18px;min-width:520px;">{th}{body}</table>'


def _bullets(items: list[str], color: str) -> str:
    if not items:
        return f'<p style="color:{_GREY};margin:4px 0 14px;">Nothing to report.</p>'
    lis = "".join(f'<li style="margin:4px 0;">{escape(x)}</li>' for x in items)
    return f'<ul style="margin:4px 0 16px;padding-left:20px;color:{color};">{lis}</ul>'


_STATUS = {"Target Hit": ("Target", _GREEN), "SL Hit": ("Stop", _RED), "Day Close": ("Day close", _GREY)}


def _trade_log(trades: list[dict], what: str = "Stock") -> str:
    if not trades:
        return f'<p style="color:{_GREY};margin:4px 0 14px;">No live trades closed today.</p>'
    rows = []
    for t in sorted(trades, key=lambda t: t["time"]):
        label, color = _STATUS.get(t.get("status"), (t.get("status", ""), _GREY))
        when = "—" if t.get("approx_time") else f"{t['time']:%H:%M}–{t['exit_time']:%H:%M}"
        rows.append([
            when, escape(t.get("stock", "")), escape(t["strategy"]),
            f'<b style="color:{_GREEN if t["side"] == "BUY" else _RED};">{t["side"]}</b>',
            qty_text(t), f"{float(t['entry']):,.2f}", f"{float(t['exit_price']):,.2f}",
            f'<span style="color:{color};">{label}</span>', f"₹{inr(t['charges'])}", _money(t["net"]),
        ])
    return _table(["Time", what, "Strategy", "Side", "Qty", "Entry ₹", "Exit ₹", "Exit", "Charges", "Net"], rows)


def _open_note(a: dict) -> str:
    if not a["open"]:
        return ""
    return (f'<p style="margin:0 0 14px;">Still open: {a["open"]} position{"s" if a["open"] != 1 else ""} holding '
            f'₹{inr(a["in_positions"])}, unrealised {_money(a["unrealized"])} before charges.</p>')


def _account_section(title: str, a: dict, today: list[dict], what: str) -> str:
    net, charges = sum(t["net"] for t in today), sum(t["charges"] for t in today)
    return f"""
<h3 style="color:#1a5276;margin:18px 0 2px;">{title}</h3>
<table style="border-collapse:collapse;margin:6px 0 10px;">
  <tr><td style="padding:4px 18px 4px 0;color:#555;">Paper account</td>
      <td style="font-size:20px;font-weight:bold;">₹{inr(a['balance'])}
        <span style="font-size:13px;color:{_GREEN if a['return_pct'] >= 0 else _RED};">{a['return_pct']:+.2f}%</span></td></tr>
  <tr><td style="padding:4px 18px 4px 0;color:#555;">Started</td>
      <td>₹{inr(a['initial'])} on {a['start']:%d %b %Y}</td></tr>
  <tr><td style="padding:4px 18px 4px 0;color:#555;">Today</td>
      <td>{_money(net)} after ₹{inr(charges)} brokerage &amp; taxes · {len(today)} trades</td></tr>
  <tr><td style="padding:4px 18px 4px 0;color:#555;">Free to trade</td><td>₹{inr(a['free'])}</td></tr>
</table>
{_trade_log(today, what)}
{_open_note(a)}"""


def build_html(ins: dict, date_label: str) -> str:
    strategies = sorted(set(ins["live_rows"]) | set(ins["opt_rows"]))
    today_rows = []
    for name in strategies:
        st, op = ins["live_rows"].get(name), ins["opt_rows"].get(name)
        today_rows.append([
            escape(name),
            f"{st['trades']} ({st['wins']}W/{st['losses']}L)" if st else "—",
            _money(st["net"]) if st else "—",
            f"{op['trades']} ({op['wins']}W/{op['losses']}L)" if op else "—",
            _money(op["net"]) if op else "—",
        ])

    limit = STRATEGY_REVIEW["max_loss_rate"]
    verdict_rows = []
    for r in ins["reviews"]:
        def src(s):
            return f"{s.loss_rate:.0f}% of {s.trades}" if s.trades else "—"
        live_tag = ' <span style="color:#7f8c8d;font-size:11px;">(live on)</span>' if r.key in ins["live_on"] else ""
        verdict_rows.append([
            escape(r.name) + live_tag,
            src(r.backtest), src(r.live), _money(r.live.net) if r.live.trades else "—",
            f'<b style="color:{_VERDICT_COLOR[r.verdict]};">{r.verdict}</b>',
        ])

    return f"""
<html><body style="font-family:Arial,sans-serif;color:{_INK};max-width:760px;">
<h2 style="color:#1a5276;margin-bottom:2px;">LIVE report</h2>
<p style="color:{_GREY};margin-top:0;">{escape(date_label)} · the paper accounts' real-time trades (not a backtest)</p>
{_account_section("Stocks", ins["account"], ins["live_today"], "Stock")}
{_account_section("Options · NIFTY &amp; BANKNIFTY", ins["options"], ins["opt_today"], "Contract")}

<h2 style="color:#1a5276;margin:26px 0 2px;">Strategy analysis</h2>
<h3 style="color:{_GREEN};margin-bottom:2px;">What went right</h3>
{_bullets(ins['right'], _INK)}
<h3 style="color:{_RED};margin-bottom:2px;">What went wrong</h3>
{_bullets(ins['wrong'], _INK)}

<h3 style="margin-bottom:2px;">Today by strategy (live)</h3>
{_table(["Strategy", "Stock trades", "Stocks net", "Option trades", "Options net"], today_rows)
 if today_rows else f'<p style="color:{_GREY};">No live trades closed today.</p>'}

<h3 style="margin-bottom:2px;">Which strategies work</h3>
<p style="font-size:12px;color:#555;margin:2px 0;">Losing = share of trades with a net loss after charges.
Backtest: last 7 days on the top stocks. Live: the stock account since it started.
Not good = more than {limit}% losing wherever there are at least {STRATEGY_REVIEW['min_trades']} trades.</p>
{_table(["Strategy", "Backtest losing", "Live losing", "Live net", "Verdict"], verdict_rows)}

<hr/>
<p style="font-size:11px;color:{_GREY};">
  Sizing: {escape(sizing_label())}, compounding, after brokerage and taxes. Nothing here is a real order.
  Auto-generated by AlgoTrading at 3:45 PM IST. The backtest P&amp;L is in the separate BACKTEST email at 4 PM.
</p>
</body></html>"""


def build_subject(ins: dict) -> str:
    n = defaultdict(int)
    for r in ins["reviews"]:
        n[r.verdict] += 1
    flags = f" · {n[NOT_GOOD]} not good" if n[NOT_GOOD] else ""
    stocks = sum(t["net"] for t in ins["live_today"])
    options = sum(t["net"] for t in ins["opt_today"])
    return (f"[AlgoTrading] LIVE report & strategy analysis — {ins['today']} · stocks {rupees_text(stocks)} · "
            f"options {rupees_text(options)}{flags}")


# ── scheduler entry point ─────────────────────────────────────────────────────

def send_strategy_analysis_email():
    """Called every minute by the scheduler (in a worker thread); sends once per trading day."""
    from email_report import _send_email  # noqa: PLC0415

    now = now_ist()
    day = f"{now:%Y-%m-%d}"
    key = f"analysis_email_sent_{day}"  # written only after the email went out
    (h0, m0), (h1, m1) = SEND_WINDOW
    if not ((h0, m0) <= (now.hour, now.minute) <= (h1, m1)) or not _is_trading_day(now):
        return
    if _is_already_sent(key) or _attempts.get(day, 0) >= MAX_ATTEMPTS:
        return
    if not _building.acquire(blocking=False):  # a slow build is still running from an earlier tick
        return
    try:
        _attempts[day] = _attempts.get(day, 0) + 1
        ins = insights(gather(now))
        _send_email(build_subject(ins), build_html(ins, now.strftime("%A, %d %b %Y")), None, None)  # raises if it fails
        _mark_sent(key)
        print(f"  [analysis_email] sent for {day}")
    except Exception as e:
        print(f"  [analysis_email] attempt {_attempts[day]}/{MAX_ATTEMPTS} failed: {e}")
    finally:
        _building.release()


_building = threading.Lock()
_attempts: dict[str, int] = {}  # day → builds tried (in memory: a restart allows MAX_ATTEMPTS more)
