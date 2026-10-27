"""
Daily live report + strategy analysis email — one email, separate from the 4 PM backtest report
(email_report.py).

Sent once per trading day between 15:45 and 15:55 IST, after the close. The live report part is the
paper account and today's live trades, trade by trade; the analysis part answers "what went right,
what went wrong, which strategies work" from three things:

  * today's live trades in the paper account (account.py: compounding, after brokerage and taxes),
  * today's backtest on the top stocks, every strategy on its own ₹ funds,
  * the Strategy Analysis verdicts (strategy_review.py): last 7 days of backtest + live since the
    account started, judged on the share of trades that lose money after charges.

gather() does the I/O; insights() and build_html() are pure, so the email can be built and checked
without sending anything.
"""

from collections import defaultdict
from html import escape

from backtest_metrics import (
    DEFAULT_FUNDS, DEFAULT_MODE, DEFAULT_SIZING, inr, rupees_text, size_trades, sizing_label, summarize,
)
from config import STRATEGY_REVIEW, _is_trading_day, now_ist
from state import _is_already_sent, _mark_sent
from strategy_review import GOOD, NOT_GOOD, TOO_EARLY, WATCH, build_reviews

SEND_WINDOW = ((15, 45), (15, 55))  # after the 15:30 close, before the 4 PM backtest report
_CHARGES_HEAVY = 0.30               # flag a day when charges eat more than 30% of the gross profit

_GREEN, _RED, _AMBER, _GREY, _INK = "#1e8449", "#c0392b", "#b9770e", "#7f8c8d", "#2c3e50"
_VERDICT_COLOR = {NOT_GOOD: _RED, WATCH: _AMBER, GOOD: _GREEN, TOO_EARLY: _GREY}


# ── data ──────────────────────────────────────────────────────────────────────

def gather(now) -> dict:
    """Backtests for every strategy, the live account and its trades. Slow (one candle fetch per
    top stock): run it in a worker thread."""
    from account import account_state, in_account                       # noqa: PLC0415
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
        "live": in_account(completed), "account": account_state(now),
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
    acct = data["account"]
    names = {r["key"]: r["display_name"] for r in data["rows"]}
    live_on = {r["key"] for r in data["rows"] if r["live_enabled"]}
    mode, amount = DEFAULT_MODE, DEFAULT_SIZING[DEFAULT_MODE]

    # today, live: the account's own trades (they shared the funds, as they really would)
    live_today = [t for t in acct["sized"] if t["trade_date"] == today]
    live_rows = {name: summarize(ts) for name, ts in _by_strategy(live_today).items()}

    # today, backtest: each strategy on its own funds
    bt_groups = _by_strategy([t for t in data["backtest"] if t.get("trade_date") == today], "strategy_key")
    bt_sized = {k: size_trades(ts, mode, amount, DEFAULT_FUNDS) for k, ts in bt_groups.items()}
    bt_rows = {names.get(k, k): summarize(ts) for k, ts in bt_sized.items() if ts}

    reviews = build_reviews(data["backtest"], data["live"], data["rows"], float(acct["initial"]))

    right, wrong = [], []
    if live_today:
        for name, s in sorted(live_rows.items(), key=lambda kv: -kv[1]["net"]):
            line = f"{name} {_made_lost(s['net'])} live today ({s['wins']}W/{s['losses']}L)"
            (right if s["net"] > 0 else wrong).append(line)
    else:
        wrong.append("No live trades closed today, so the paper account didn't move.")
    for name, s in sorted(bt_rows.items(), key=lambda kv: -kv[1]["net"]):
        line = (f"In today's backtest, {name} would have {_made_lost(s['net'])} "
                f"over {s['trades']} trade{'s' if s['trades'] != 1 else ''} ({s['win_rate']:.0f}% won)")
        (right if s["net"] > 0 else wrong).append(line)

    every_today = live_today + [t for ts in bt_sized.values() for t in ts]
    if every_today:
        best = max(every_today, key=lambda t: t["net"])
        worst = min(every_today, key=lambda t: t["net"])
        src = lambda t: "live" if t in live_today else "backtest"  # noqa: E731
        if best["net"] > 0:
            right.append(f"Best trade: {best.get('stock', '?')} {best['side']} ({best['strategy']}, {src(best)}) "
                         f"{rupees_text(best['net'])}")
        if worst["net"] < 0:
            wrong.append(f"Worst trade: {worst.get('stock', '?')} {worst['side']} ({worst['strategy']}, {src(worst)}) "
                         f"{rupees_text(worst['net'])}")

    day = summarize(live_today) if live_today else summarize([t for ts in bt_sized.values() for t in ts])
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
        "today": today, "account": acct, "live_today": live_today, "live_rows": live_rows,
        "bt_rows": bt_rows, "reviews": reviews, "right": right, "wrong": wrong,
        "live_on": live_on, "backtest_report": data["backtest_report"],
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


def _trade_log(trades: list[dict]) -> str:
    if not trades:
        return f'<p style="color:{_GREY};margin:4px 0 14px;">No live trades closed today.</p>'
    rows = []
    for t in sorted(trades, key=lambda t: t["time"]):
        label, color = _STATUS.get(t.get("status"), (t.get("status", ""), _GREY))
        when = "—" if t.get("approx_time") else f"{t['time']:%H:%M}–{t['exit_time']:%H:%M}"
        rows.append([
            when, escape(t.get("stock", "")), escape(t["strategy"]),
            f'<b style="color:{_GREEN if t["side"] == "BUY" else _RED};">{t["side"]}</b>',
            f"{t['qty']:,}", f"{float(t['entry']):,.2f}", f"{float(t['exit_price']):,.2f}",
            f'<span style="color:{color};">{label}</span>', f"₹{inr(t['charges'])}", _money(t["net"]),
        ])
    return _table(["Time", "Stock", "Strategy", "Side", "Qty", "Entry ₹", "Exit ₹", "Exit", "Charges", "Net"], rows)


def _open_note(a: dict) -> str:
    if not a["open"]:
        return ""
    return (f'<p style="margin:0 0 14px;">Still open: {a["open"]} position{"s" if a["open"] != 1 else ""} holding '
            f'₹{inr(a["in_positions"])}, unrealised {_money(a["unrealized"])} before charges.</p>')


def build_html(ins: dict, date_label: str) -> str:
    a = ins["account"]
    live_today_net = sum(t["net"] for t in ins["live_today"])
    live_today_charges = sum(t["charges"] for t in ins["live_today"])

    strategies = sorted(set(ins["live_rows"]) | set(ins["bt_rows"]))
    today_rows = []
    for name in strategies:
        lv, bt = ins["live_rows"].get(name), ins["bt_rows"].get(name)
        today_rows.append([
            escape(name),
            f"{lv['trades']} ({lv['wins']}W/{lv['losses']}L)" if lv else "—",
            _money(lv["net"]) if lv else "—",
            f"{bt['trades']} ({bt['wins']}W/{bt['losses']}L)" if bt else "—",
            _money(bt["net"]) if bt else "—",
        ])

    limit = STRATEGY_REVIEW["max_loss_rate"]
    verdict_rows = []
    for r in ins["reviews"]:
        def src(s):
            return f"{s.loss_rate:.0f}% of {s.trades}" if s.trades else "—"
        live_tag = ' <span style="color:#7f8c8d;font-size:11px;">(live on)</span>' if r.key in ins["live_on"] else ""
        verdict_rows.append([
            escape(r.name) + live_tag,
            src(r.backtest), _money(r.backtest.net) if r.backtest.trades else "—",
            src(r.live), _money(r.live.net) if r.live.trades else "—",
            f'<b style="color:{_VERDICT_COLOR[r.verdict]};">{r.verdict}</b>',
        ])

    rep = ins["backtest_report"]
    loaded = len(rep.get("loaded", []))
    return f"""
<html><body style="font-family:Arial,sans-serif;color:{_INK};max-width:760px;">
<h2 style="color:#1a5276;margin-bottom:2px;">Live report</h2>
<p style="color:{_GREY};margin-top:0;">{escape(date_label)}</p>

<table style="border-collapse:collapse;margin:10px 0 18px;">
  <tr><td style="padding:4px 18px 4px 0;color:#555;">Paper account</td>
      <td style="font-size:20px;font-weight:bold;">₹{inr(a['balance'])}
        <span style="font-size:13px;color:{_GREEN if a['return_pct'] >= 0 else _RED};">{a['return_pct']:+.2f}%</span></td></tr>
  <tr><td style="padding:4px 18px 4px 0;color:#555;">Started</td>
      <td>₹{inr(a['initial'])} on {a['start']:%d %b %Y}</td></tr>
  <tr><td style="padding:4px 18px 4px 0;color:#555;">Live today</td>
      <td>{_money(live_today_net)} after ₹{inr(live_today_charges)} brokerage &amp; taxes · {len(ins['live_today'])} trades</td></tr>
  <tr><td style="padding:4px 18px 4px 0;color:#555;">Free to trade</td><td>₹{inr(a['free'])}</td></tr>
</table>

<h3 style="margin-bottom:2px;">Live trades today</h3>
{_trade_log(ins['live_today'])}
{_open_note(a)}

<h2 style="color:#1a5276;margin:26px 0 2px;">Strategy analysis</h2>
<h3 style="color:{_GREEN};margin-bottom:2px;">What went right</h3>
{_bullets(ins['right'], _INK)}
<h3 style="color:{_RED};margin-bottom:2px;">What went wrong</h3>
{_bullets(ins['wrong'], _INK)}

<h3 style="margin-bottom:2px;">Today by strategy</h3>
{_table(["Strategy", "Live trades", "Live net", "Backtest trades", "Backtest net"], today_rows)
 if today_rows else f'<p style="color:{_GREY};">No trades today, live or in the backtest.</p>'}

<h3 style="margin-bottom:2px;">Which strategies work</h3>
<p style="font-size:12px;color:#555;margin:2px 0;">Losing = share of trades with a net loss after charges.
Backtest: last 7 days on the top stocks. Live: since the paper account started.
Not good = more than {limit}% losing wherever there are at least {STRATEGY_REVIEW['min_trades']} trades.</p>
{_table(["Strategy", "Backtest losing", "Backtest net", "Live losing", "Live net", "Verdict"], verdict_rows)}

<hr/>
<p style="font-size:11px;color:{_GREY};">
  Sizing: {escape(sizing_label())}, compounding, after brokerage and taxes. {loaded} stocks backtested.
  Nothing here is a real order. Auto-generated by AlgoTrading at 3:45 PM IST — the backtest P&amp;L report is a separate email.
</p>
</body></html>"""


def build_subject(ins: dict) -> str:
    a = ins["account"]
    n = defaultdict(int)
    for r in ins["reviews"]:
        n[r.verdict] += 1
    flags = f" · {n[NOT_GOOD]} not good" if n[NOT_GOOD] else ""
    today_net = sum(t["net"] for t in ins["live_today"])
    return (f"[AlgoTrading] Live report & strategy analysis — {ins['today']} · today {rupees_text(today_net)} · "
            f"account ₹{inr(a['balance'])} ({a['return_pct']:+.2f}%){flags}")


# ── scheduler entry point ─────────────────────────────────────────────────────

def send_strategy_analysis_email():
    """Called every minute by the scheduler (in a worker thread); sends once per trading day."""
    from email_report import _send_email  # noqa: PLC0415

    now = now_ist()
    key = f"analysis_email_{now:%Y-%m-%d}"
    (h0, m0), (h1, m1) = SEND_WINDOW
    if not ((h0, m0) <= (now.hour, now.minute) <= (h1, m1)) or not _is_trading_day(now):
        return
    if _is_already_sent(key):
        return
    _mark_sent(key)  # mark first: a slow build must not start a second one on the next tick
    try:
        ins = insights(gather(now))
        _send_email(build_subject(ins), build_html(ins, now.strftime("%A, %d %b %Y")), None, None)
    except Exception as e:
        print(f"  [analysis_email] failed: {e}")
