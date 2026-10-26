"""
Shared pieces of the Backtest P&L and Live P&L pages: CSS, number formatting, KPI tiles, the
summary / trade tables, the clickable strategy table, the equity curve and the sizing controls.
Inputs are trades already sized by backtest_metrics.size_trades().
"""

from html import escape

import plotly.graph_objects as go
from nicegui import ui

from backtest_metrics import DEFAULT_SIZING, SIZING_MODES, equity_curve, inr

# Fixed hexes: Plotly can't read the theme's CSS variables. Mid-tones that read on dark and light.
_LINE = "#4f8cff"
_INK = "#8a97a3"
_GRID = "rgba(138,151,163,0.15)"


# ── Formatting ────────────────────────────────────────────────────────────────

def rs(v: float, sign: bool = False) -> str:
    s = f"₹{inr(v)}"
    if sign:
        return ("+" if v > 0 else "−" if v < 0 else "") + s
    return ("−" if v < 0 else "") + s


def tone(v: float) -> str:
    return "bt-up" if v > 0 else "bt-down" if v < 0 else ""


def pf(v) -> str:
    return "—" if v is None else f"{v:.2f}"


STATUS = {"Open": ("Open", "bt-dim"), "Target Hit": ("Target", "bt-up"), "SL Hit": ("Stop", "bt-down"), "Day Close": ("Day close", "bt-dim")}

CSS = """
<style>
  .bt-sub { font-family:var(--at-mono); font-size:11px; color:var(--at-fg-faint); letter-spacing:.02em; }
  .bt-bar { display:grid; grid-template-columns:repeat(auto-fit, minmax(170px, 1fr)); gap:10px; align-items:center; }
  .bt-bar > * { min-width:0; }
  .bt-bar .q-field__native, .bt-bar .q-field__input { font-family:var(--at-sans) !important; }
  .bt-bar .q-field--dense .q-field__control { min-height:40px !important; height:40px !important; }
  .bt-size { display:flex; gap:8px; align-items:center; }
  @media (min-width:700px) { .bt-size { grid-column:span 2; } }
  .bt-seg { flex-shrink:0; border:1px solid var(--at-line2); border-radius:var(--at-radius-sm); overflow:hidden; }
  .bt-seg .q-btn { font-size:12px; font-weight:600; padding:0 10px; min-height:38px; }
  .bt-status { font-family:var(--at-mono); font-size:10.5px; color:var(--at-fg-faint); line-height:1.6; }
  .bt-status b { color:var(--at-fg-dim); font-weight:500; }
  .bt-warn { color:var(--at-warn); }
  .bt-tiles { display:grid; grid-template-columns:repeat(auto-fit, minmax(150px, 1fr)); gap:10px; }
  .bt-tile { background:var(--at-bg1); border:1px solid var(--at-line); border-radius:var(--at-radius); padding:12px 14px; min-width:0; }
  .bt-tile.hero { grid-column:span 2; }
  @media (max-width:520px) { .bt-tile.hero { grid-column:1 / -1; } }
  .bt-k { font-family:var(--at-mono); font-size:10px; letter-spacing:.08em; text-transform:uppercase; color:var(--at-fg-faint); }
  .bt-v { font-family:var(--at-sans); font-size:22px; font-weight:700; color:var(--at-fg); margin-top:4px; line-height:1.15;
          font-variant-numeric:tabular-nums; }
  .bt-tile.hero .bt-v { font-size:30px; }
  .bt-s { font-size:11px; color:var(--at-fg-dim); margin-top:3px; }
  .bt-up { color:var(--at-up) !important; }
  .bt-down { color:var(--at-down) !important; }
  .bt-dim { color:var(--at-fg-dim) !important; }
  .bt-card { background:var(--at-bg1); border:1px solid var(--at-line); border-radius:var(--at-radius); padding:14px 16px; }
  .bt-h { font-size:13px; font-weight:700; color:var(--at-fg); margin-bottom:2px; }
  .bt-hs { font-size:11.5px; color:var(--at-fg-dim); margin-bottom:8px; }
  .bt-charges summary { cursor:pointer; font-family:var(--at-mono); font-size:10.5px; color:var(--at-fg-dim); letter-spacing:.04em; }
  .bt-charges .row { display:flex; flex-wrap:wrap; gap:6px 22px; margin-top:8px; font-family:var(--at-mono); font-size:11.5px; color:var(--at-fg); }
  .bt-charges .row span { color:var(--at-fg-faint); margin-right:6px; }
  .bt-wrap { width:100%; overflow-x:auto; border:1px solid var(--at-line); border-radius:var(--at-radius); }
  .bt-table { width:100%; border-collapse:collapse; font-size:12.5px; }
  .bt-table th { text-align:left; font-family:var(--at-mono); font-size:10px; font-weight:500; letter-spacing:.06em;
                 text-transform:uppercase; color:var(--at-fg-faint); padding:8px 10px; border-bottom:1px solid var(--at-line);
                 white-space:nowrap; background:var(--at-bg1); }
  .bt-table td { padding:8px 10px; border-bottom:1px solid var(--at-line); color:var(--at-fg); white-space:nowrap; }
  .bt-table tr:last-child td { border-bottom:none; }
  .bt-table .n { text-align:right; font-family:var(--at-mono); font-variant-numeric:tabular-nums; }
  .bt-table th.n { text-align:right; }
  .bt-table tr.click { cursor:pointer; }
  .bt-table tr.click:hover td { background:color-mix(in srgb, var(--at-accent) 6%, transparent); }
  .bt-table tr.sel td { background:color-mix(in srgb, var(--at-accent) 10%, transparent); }
  .bt-table tr.sel td:first-child { box-shadow:inset 2px 0 0 var(--at-accent); }
  .bt-badge { display:inline-block; font-family:var(--at-mono); font-size:10.5px; font-weight:600; padding:1px 7px;
              border-radius:4px; border:1px solid currentColor; }
  .bt-netcell { display:flex; align-items:center; justify-content:flex-end; gap:8px; }
  .bt-track { width:70px; height:6px; position:relative; flex-shrink:0; }
  .bt-track::before { content:''; position:absolute; left:50%; top:-2px; bottom:-2px; width:1px; background:var(--at-line2); }
  .bt-fill { position:absolute; top:0; height:6px; border-radius:3px; }
  .bt-empty { font-size:13px; color:var(--at-fg-dim); padding:28px 12px; text-align:center; }
  @media (max-width: 899px) {
    .bt-wrap { border:none; overflow:visible; }
    .bt-table thead { display:none; }
    .bt-table, .bt-table tbody { display:block; width:100%; }
    .bt-table tr { display:grid; grid-template-columns:1fr 1fr; gap:8px 14px; padding:12px 14px; margin-bottom:10px;
                   background:var(--at-bg1); border:1px solid var(--at-line); border-radius:var(--at-radius); }
    .bt-table td { display:block; padding:0; border:none !important; text-align:left !important; white-space:normal; background:none !important; }
    .bt-table td::before { content:attr(data-label); display:block; font-family:var(--at-mono); font-size:9.5px;
                           letter-spacing:.06em; text-transform:uppercase; color:var(--at-fg-faint); margin-bottom:2px; }
    .bt-table td.wide { grid-column:1 / -1; font-weight:700; }
    .bt-table td.wide::before { display:none; }
    .bt-netcell { justify-content:flex-start; }
    .bt-table tr.sel { border-color:var(--at-accent); }
  }
</style>
"""


def td(label: str, content: str, cls: str = "") -> str:
    return f'<td data-label="{escape(label)}" class="{cls}">{content}</td>'


def net_bar(net: float, scale: float) -> str:
    """Text value plus a diverging bar: right/green for profit, left/red for loss, centred on zero."""
    w = 0 if not scale else min(50, abs(net) / scale * 50)
    side = f"left:50%; width:{w:.1f}%; background:var(--at-up);" if net >= 0 else \
           f"right:50%; width:{w:.1f}%; background:var(--at-down);"
    return (f'<div class="bt-netcell"><span class="{tone(net)}">{rs(net, sign=True)}</span>'
            f'<span class="bt-track"><span class="bt-fill" style="{side}"></span></span></div>')


def summary_table(groups: list[tuple[str, dict]], first_col: str) -> str:
    scale = max((abs(s["net"]) for _, s in groups), default=0)
    head = (f'<tr><th>{first_col}</th><th class="n">Trades</th><th class="n">Win rate</th>'
            '<th class="n">Profit factor</th><th class="n">Avg win</th><th class="n">Avg loss</th>'
            '<th class="n">Charges</th><th class="n">Net P&amp;L</th></tr>')
    rows = "".join(
        "<tr>"
        + td(first_col, escape(name), "wide")
        + td("Trades", f'{s["trades"]} <span class="bt-dim">({s["wins"]}W/{s["losses"]}L)</span>', "n")
        + td("Win rate", f'{s["win_rate"]:.0f}%', "n")
        + td("Profit factor", pf(s["profit_factor"]), "n")
        + td("Avg win", rs(s["avg_win"]), "n bt-up")
        + td("Avg loss", rs(s["avg_loss"]), "n bt-down")
        + td("Charges", rs(s["charges"]), "n bt-dim")
        + td("Net P&L", net_bar(s["net"], scale), "n")
        + "</tr>"
        for name, s in groups
    )
    return f'<div class="bt-wrap"><table class="bt-table"><thead>{head}</thead><tbody>{rows}</tbody></table></div>'


def trades_table(trades: list[dict], show_stock: bool) -> str:
    head = ("<tr><th>Entry</th>" + ("<th>Stock</th>" if show_stock else "") +
            '<th>Strategy</th><th>Side</th><th class="n">Qty</th><th class="n">Entry ₹</th>'
            '<th class="n">Exit ₹</th><th>Exit</th><th class="n">Charges</th><th class="n">Net</th>'
            '<th class="n">Return</th></tr>')
    body = []
    for t in sorted(trades, key=lambda t: t["time"], reverse=True):
        label, cls = STATUS.get(t["status"], (t["status"], "bt-dim"))
        exit_t = None if t.get("approx_time") else t.get("exit_time")
        exit_txt = f'<span class="bt-badge {cls}">{label}</span>'
        if hasattr(exit_t, "strftime"):
            exit_txt += f' <span class="bt-dim">{exit_t.strftime("%H:%M")}</span>'
        side_cls = "bt-up" if t["side"] == "BUY" else "bt-down"
        body.append(
            "<tr>"
            + td("Entry", t["time"].strftime("%d %b" if t.get("approx_time") else "%d %b · %H:%M"), "wide")
            + (td("Stock", escape(t.get("stock", ""))) if show_stock else "")
            + td("Strategy", escape(t["strategy"]))
            + td("Side", f'<b class="{side_cls}">{t["side"]}</b>')
            + td("Qty", f'{t["qty"]:,}', "n")
            + td("Entry ₹", f'{float(t["entry"]):,.2f}', "n")
            + td("Exit ₹", f'{float(t["exit_price"]):,.2f}', "n")
            + td("Exit", exit_txt)
            + td("Charges", rs(t["charges"]), "n bt-dim")
            + td("Net", f'<b>{rs(t["net"], sign=True)}</b>', f"n {tone(t['net'])}")
            + td("Return", f'{t["ret_pct"]:+.2f}%', f"n {tone(t['net'])}")
            + "</tr>"
        )
    return f'<div class="bt-wrap"><table class="bt-table"><thead>{head}</thead><tbody>{"".join(body)}</tbody></table></div>'


def equity_figure(trades: list[dict]) -> go.Figure:
    curve = equity_curve(trades)
    xs = list(range(1, len(curve) + 1))
    ys = [round(total, 2) for _, total in curve]
    hover = [
        f"#{i} · {t['exit_time'].strftime('%d %b' if t.get('approx_time') else '%d %b %H:%M') if hasattr(t.get('exit_time'), 'strftime') else ''}<br>"
        f"{escape(t.get('stock', ''))} · {escape(t['strategy'])}<br>"
        f"Trade {rs(t['net'], sign=True)} · Total {rs(total, sign=True)}"
        for i, (t, total) in zip(xs, curve)
    ]
    fig = go.Figure(go.Scatter(
        x=[0] + xs, y=[0] + ys, mode="lines+markers",
        line=dict(color=_LINE, width=2), marker=dict(size=6, color=_LINE),
        text=["Start"] + hover, hovertemplate="%{text}<extra></extra>",
    ))
    fig.add_hline(y=0, line=dict(color=_INK, width=1, dash="dot"))
    fig.update_layout(
        height=240, margin=dict(l=8, r=8, t=8, b=8), showlegend=False,
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Manrope, sans-serif", color=_INK, size=11),
        hoverlabel=dict(bgcolor="#141a1f", bordercolor="#2a353f", font=dict(color="#e6edf3", size=12)),
        xaxis=dict(gridcolor=_GRID, showline=False, fixedrange=True, title=dict(text="Trades, in exit order", font=dict(size=10))),
        yaxis=dict(gridcolor=_GRID, zeroline=False, tickprefix="₹", fixedrange=True),
    )
    return fig


def strategy_table(groups: dict, names: list[str], selected: str, on_pick):
    """One row per strategy in `names` (summaries in `groups`); clicking a row calls on_pick(name).
    Built from elements, not one HTML string, so each row can take a click."""
    names = sorted(names, key=lambda n: groups[n]["net"] if n in groups else 0, reverse=True)
    scale = max((abs(g["net"]) for g in groups.values()), default=0)

    def cell(label, content, cls=""):
        with ui.element("td").classes(cls).props(f'data-label="{label}"'):
            ui.html(content, tag="span")

    ui.html("Click a strategy to filter the page by it; click again to clear.").classes("bt-hs")
    with ui.element("div").classes("bt-wrap"):
        with ui.element("table").classes("bt-table"):
            with ui.element("thead"), ui.element("tr"):
                for h in ("Strategy", "Trades", "Win rate", "Profit factor", "Avg win", "Avg loss", "Charges", "Net P&L"):
                    with ui.element("th").classes("" if h == "Strategy" else "n"):
                        ui.label(h)
            with ui.element("tbody"):
                for name in names:
                    g = groups.get(name)
                    row = ui.element("tr").classes("click" + (" sel" if selected == name else ""))
                    row.on("click", lambda n=name: on_pick(n))
                    with row:
                        cell("Strategy", escape(name), "wide")
                        if not g:
                            cell("Trades", '<span class="bt-dim">no trades</span>', "n")
                            continue
                        cell("Trades", f'{g["trades"]} <span class="bt-dim">({g["wins"]}W/{g["losses"]}L)</span>', "n")
                        cell("Win rate", f'{g["win_rate"]:.0f}%', "n")
                        cell("Profit factor", pf(g["profit_factor"]), "n")
                        cell("Avg win", rs(g["avg_win"]), "n bt-up")
                        cell("Avg loss", rs(g["avg_loss"]), "n bt-down")
                        cell("Charges", rs(g["charges"]), "n bt-dim")
                        cell("Net P&L", net_bar(g["net"], scale), "n")


def kpi_tiles(s: dict) -> str:
    avg_cap = f" · avg {rs(s['capital'])} per trade" if s["trades"] else ""
    return f"""
    <div class="bt-tiles">
      <div class="bt-tile hero"><div class="bt-k">Net P&amp;L</div>
        <div class="bt-v {tone(s['net'])}">{rs(s['net'], sign=True)}</div>
        <div class="bt-s">gross {rs(s['gross'], sign=True)} − charges {rs(s['charges'])}{avg_cap}</div></div>
      <div class="bt-tile"><div class="bt-k">Win rate</div><div class="bt-v">{s['win_rate']:.0f}%</div>
        <div class="bt-s">{s['wins']} won · {s['losses']} lost · {s['trades']} trades</div></div>
      <div class="bt-tile"><div class="bt-k">Profit factor</div><div class="bt-v">{pf(s['profit_factor'])}</div>
        <div class="bt-s">avg win {rs(s['avg_win'])} · avg loss {rs(s['avg_loss'])}</div></div>
      <div class="bt-tile"><div class="bt-k">Per trade</div>
        <div class="bt-v {tone(s['expectancy'])}">{rs(s['expectancy'], sign=True)}</div>
        <div class="bt-s">average net · {s['avg_ret_pct']:+.2f}% on capital</div></div>
      <div class="bt-tile"><div class="bt-k">Max drawdown</div>
        <div class="bt-v {'bt-down' if s['max_drawdown'] else ''}">{rs(-s['max_drawdown'])}</div>
        <div class="bt-s">worst drop from a high</div></div>
    </div>"""


def charges_html(s: dict) -> str:
    cp = s["charge_parts"]
    parts = "".join(f"<div><span>{k.upper()}</span>₹{cp[k]:,.2f}</div>" for k in cp)
    return (f'<details class="bt-charges mt-2"><summary>CHARGES BREAKDOWN · {rs(s["charges"])}</summary>'
            f'<div class="row">{parts}</div></details>')


_AMOUNT_LABEL = {"risk": "Max loss ₹ per trade", "capital": "₹ per trade", "shares": "Shares per trade"}
_AMOUNT_STEP = {"risk": 100, "capital": 1000, "shares": 1}


def sizing_controls(st: dict, on_change):
    """Risk ₹ / ₹-per-trade / shares toggle plus amount box. Updates st["mode"] / st["amount"],
    then calls on_change()."""
    with ui.element("div").classes("bt-size"):
        mode_tgl = ui.toggle(SIZING_MODES, value=st["mode"]) \
            .props("dense no-caps unelevated toggle-color=primary").classes("bt-seg")
        amount_in = ui.number(label=_AMOUNT_LABEL[st["mode"]], value=st["amount"], min=1,
                              step=_AMOUNT_STEP[st["mode"]], format="%.0f") \
            .props("outlined dense").classes("flex-1 min-w-[90px]")

    def _on_mode(e):
        st["mode"] = e.value
        st["amount"] = DEFAULT_SIZING[e.value]
        amount_in.props["label"] = _AMOUNT_LABEL[e.value]
        amount_in.props["step"] = _AMOUNT_STEP[e.value]
        amount_in.update()
        amount_in.set_value(st["amount"])
        on_change()

    def _on_amount(e):
        try:
            v = max(1, int(e.value or 0))
        except (TypeError, ValueError):
            return
        if v != st["amount"]:
            st["amount"] = v
            on_change()

    mode_tgl.on_value_change(_on_mode)
    amount_in.on_value_change(_on_amount)
