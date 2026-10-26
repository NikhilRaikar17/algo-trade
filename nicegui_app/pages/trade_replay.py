"""
Trade Replay — Monte Carlo "time machine" for one trade on NSE 5-minute bars.

Pick a stock and a plan (entry, stop, target, entry time) — or prefill it from a live
signal — and the rest of today's session is replayed thousands of times from the stock's
own last ~60 days of 5-minute bars (replay_engine.py). Shows the odds of target first,
stop first or neither by the exit time, a fan chart of the simulated price, and the same
trade re-run on every past session. A simulation, not a prediction.
"""

import asyncio
from datetime import time

import pandas as pd
import plotly.graph_objects as go
from nicegui import ui

from config import now_ist
from data import fetch_stock_candles_history, STOCK_WATCH_GROUPS
from db import get_active_top_stocks
from live_signals import get_today_signals
from replay_engine import Plan, ReplayError, run_replay, SESSION_OPEN

# Fixed hexes: Plotly can't read the theme's CSS variables. Mid-tones that read on dark and light.
_FAN = "#4f8cff"
_TARGET = "#00b377"
_STOP = "#e5484d"
_INK = "#8a97a3"
_GRID = "rgba(138,151,163,0.15)"

_EXIT_OPTIONS = {"15:15": "15:15 (square-off)", "15:00": "15:00", "14:30": "14:30"}
_REPLAY_OPTIONS = {2000: "2,000", 10000: "10,000", 25000: "25,000"}

_CSS = """
<style>
  .rp-tiles { display:grid; grid-template-columns:repeat(auto-fit, minmax(150px, 1fr)); gap:10px; }
  .rp-tile { background:var(--at-bg1); border:1px solid var(--at-line); border-radius:var(--at-radius); padding:12px 14px; }
  .rp-tile-k { font-family:var(--at-mono); font-size:10px; letter-spacing:.08em; text-transform:uppercase; color:var(--at-fg-faint); }
  .rp-tile-v { font-family:var(--at-cond); font-size:24px; font-weight:600; color:var(--at-fg); line-height:1.2; margin-top:4px; }
  .rp-tile-s { font-size:11px; color:var(--at-fg-dim); margin-top:2px; }
  .rp-swatch { display:inline-block; width:8px; height:8px; border-radius:2px; margin-right:6px; vertical-align:middle; }
  .rp-verdict { background:var(--at-bg1); border:1px solid var(--at-line); border-left:3px solid var(--at-info);
                border-radius:var(--at-radius); padding:12px 14px; font-size:14px; color:var(--at-fg); }
  .rp-note { font-size:12px; color:var(--at-fg-dim); margin-top:4px; }
  .rp-foot { font-family:var(--at-mono); font-size:10.5px; color:var(--at-fg-faint); line-height:1.6; }
  .rp-form .q-field { min-width:120px; }
</style>
"""


def _stock_options() -> dict[str, str]:
    """security_id → name: watch-list stocks plus today's active top stocks."""
    opts = {}
    for grp in STOCK_WATCH_GROUPS:
        for s in grp["stocks"]:
            opts[s["security_id"]] = s["name"]
    try:
        for s in get_active_top_stocks():
            opts.setdefault(s["security_id"], s["name"])
    except Exception:
        pass
    return dict(sorted(opts.items(), key=lambda kv: kv[1]))


def _round_to_grid(t) -> time:
    """Snap a time down to the 5-minute grid starting 09:15."""
    m = t.hour * 60 + t.minute
    base = SESSION_OPEN.hour * 60 + SESSION_OPEN.minute
    m = base + max(0, (m - base) // 5 * 5)
    return time(m // 60, m % 60)


def _default_entry_time() -> str:
    """Latest closed 5-minute bar today during the session, else 10:15."""
    now = now_ist()
    if time(9, 20) <= now.time() < time(15, 25):
        return _round_to_grid(now.time()).strftime("%H:%M")
    return "10:15"


def _live_signals(name_to_sid: dict[str, str]) -> dict[str, dict]:
    """label → plan fields for today's open live signals on stocks we can fetch. Blocking."""
    out = {}
    try:
        active, _, _ = get_today_signals()
    except Exception:
        return out
    for t in active:
        sid = name_to_sid.get(t.get("symbol", ""))
        # Most strategies stamp the signal bar as "time"; ABCD trades carry it on the D swing point
        ts = t.get("time") or (t.get("D") or {}).get("time")
        if not sid or ts is None or not all(k in t for k in ("entry", "target", "stop_loss")):
            continue
        # The signal fires on a bar's close: entry time = signal bar start + 5 minutes
        try:
            bar_close = (pd.Timestamp(ts) + pd.Timedelta(minutes=5)).time()
        except Exception:
            continue
        side = "BUY" if t["target"] > t["entry"] else "SELL"
        label = f"{t.get('strategy', '?')} · {t['symbol']} · {side} @ {t['entry']:.2f} ({bar_close.strftime('%H:%M')})"
        out[label] = {
            "sid": sid, "entry": float(t["entry"]), "stop": float(t["stop_loss"]),
            "target": float(t["target"]), "entry_time": _round_to_grid(bar_close).strftime("%H:%M"),
        }
    return out


def _fan_chart(result, plan: Plan) -> go.Figure:
    times = [b["time"] for b in result.bands]
    fig = go.Figure()
    # 90% band, then 50% band, then the median — one hue, darker toward the middle
    fig.add_trace(go.Scatter(x=times, y=[b["p95"] for b in result.bands], mode="lines",
                             line=dict(width=0), hoverinfo="skip", showlegend=False))
    fig.add_trace(go.Scatter(x=times, y=[b["p5"] for b in result.bands], mode="lines",
                             line=dict(width=0), fill="tonexty", fillcolor="rgba(79,140,255,0.12)",
                             name="90% of replays", hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=times, y=[b["p75"] for b in result.bands], mode="lines",
                             line=dict(width=0), hoverinfo="skip", showlegend=False))
    fig.add_trace(go.Scatter(x=times, y=[b["p25"] for b in result.bands], mode="lines",
                             line=dict(width=0), fill="tonexty", fillcolor="rgba(79,140,255,0.28)",
                             name="Middle 50%", hoverinfo="skip"))
    fig.add_trace(go.Scatter(
        x=times, y=[b["p50"] for b in result.bands], mode="lines", line=dict(color=_FAN, width=2),
        name="Median",
        customdata=[[b["p5"], b["p25"], b["p75"], b["p95"]] for b in result.bands],
        hovertemplate=("Median ₹%{y:.2f}<br>Middle 50% ₹%{customdata[1]:.2f}–₹%{customdata[2]:.2f}"
                       "<br>90% ₹%{customdata[0]:.2f}–₹%{customdata[3]:.2f}<extra></extra>"),
    ))
    for y, color, dash, label in (
        (plan.target, _TARGET, "solid", f"Target ₹{plan.target:.2f}"),
        (plan.entry, _INK, "dot", f"Entry ₹{plan.entry:.2f}"),
        (plan.stop, _STOP, "solid", f"Stop ₹{plan.stop:.2f}"),
    ):
        fig.add_hline(y=y, line=dict(color=color, width=1.5, dash=dash),
                      annotation=dict(text=label, font=dict(color=_INK, size=11), xanchor="left"),
                      annotation_position="right")
    fig.update_layout(
        height=360, margin=dict(l=8, r=110, t=8, b=8),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="DM Sans, sans-serif", color=_INK, size=11),
        hovermode="x unified",
        hoverlabel=dict(bgcolor="#141a1f", bordercolor="#2a353f", font=dict(color="#e6edf3", size=12)),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0, font=dict(color=_INK)),
        xaxis=dict(gridcolor=_GRID, showline=False, nticks=10, fixedrange=True,
                   showspikes=True, spikemode="across", spikethickness=1, spikedash="dot", spikecolor=_INK),
        yaxis=dict(gridcolor=_GRID, zeroline=False, tickprefix="₹", fixedrange=True),
    )
    return fig


def render_trade_replay_tab(container):
    """Build the Trade Replay page. Returns an async refresh() closure."""
    stocks = _stock_options()
    name_to_sid = {v: k for k, v in stocks.items()}
    first_sid = next(iter(stocks), None)

    with container:
        ui.add_head_html(_CSS)
        ui.label("Trade Replay").classes("text-xl font-bold mb-1")
        ui.label(
            "Replays the rest of today's session thousands of times from the stock's own last 60 days "
            "of 5-minute bars, and re-runs the same trade on each of those days. A simulation, not a prediction."
        ).classes("text-sm text-gray-500 mb-3")

        with ui.row().classes("items-center gap-3 mb-2 w-full"):
            ui.label("From a live signal:").classes("text-sm font-medium text-gray-700")
            signal_select = ui.select({}, value=None, label="").props(
                'outlined dense clearable options-dense placeholder="Pick one, or enter a plan below"'
            ).classes("min-w-[420px]")

        with ui.row().classes("rp-form items-end gap-3 flex-wrap mb-4"):
            stock_select = ui.select(stocks, value=first_sid, label="Stock").props(
                "outlined dense use-input input-debounce=0"
            ).classes("w-48")
            entry_in = ui.number("Entry ₹", format="%.2f", step=0.05).props("outlined dense").classes("w-28")
            stop_in = ui.number("Stop ₹", format="%.2f", step=0.05).props("outlined dense").classes("w-28")
            target_in = ui.number("Target ₹", format="%.2f", step=0.05).props("outlined dense").classes("w-28")
            time_in = ui.input("Entry time (IST)", value=_default_entry_time()).props(
                'outlined dense mask="##:##"'
            ).classes("w-32").tooltip("Close time of the entry bar, e.g. 10:15")
            exit_select = ui.select(_EXIT_OPTIONS, value="15:15", label="Exit by").props("outlined dense").classes("w-52")
            replays_select = ui.select(_REPLAY_OPTIONS, value=10000, label="Replays").props("outlined dense").classes("w-28")
            seed_in = ui.number("Seed", value=19, format="%d", min=0).props("outlined dense").classes("w-20")
            run_btn = ui.button("Run replay", icon="replay").props("unelevated no-caps color=primary")

        results = ui.element("div").classes("w-full")
        with results:
            ui.label("Enter a plan and press Run replay.").classes("text-sm text-gray-500 italic")

    def _fill_from_signal(e):
        sig = signals.get(e.value) if e.value else None
        if not sig:
            return
        stock_select.set_value(sig["sid"])
        entry_in.set_value(round(sig["entry"], 2))
        stop_in.set_value(round(sig["stop"], 2))
        target_in.set_value(round(sig["target"], 2))
        time_in.set_value(sig["entry_time"])

    signal_select.on_value_change(_fill_from_signal)
    signals: dict[str, dict] = {}

    def _show_error(msg):
        results.clear()
        with results:
            ui.label(msg).classes("text-sm text-orange-500")

    async def _run():
        sid = stock_select.value
        if not sid:
            _show_error("Pick a stock.")
            return
        if None in (entry_in.value, stop_in.value, target_in.value):
            _show_error("Enter the entry, stop and target prices.")
            return
        try:
            hh, mm = (int(x) for x in (time_in.value or "").split(":"))
            plan = Plan(
                entry=float(entry_in.value), stop=float(stop_in.value), target=float(target_in.value),
                entry_time=time(hh, mm), exit_time=time(*map(int, exit_select.value.split(":"))),
            )
            plan.validate()
        except ValueError as e:
            _show_error(str(e) if isinstance(e, ReplayError) else "Entry time must be HH:MM, e.g. 10:15.")
            return

        n_replays, seed = int(replays_select.value), int(seed_in.value or 0)
        stock_name = stocks.get(sid, sid)
        results.clear()
        with results:
            ui.spinner("dots", size="lg").classes("mx-auto my-6")
            ui.label(f"Fetching 60 days of 5-minute bars for {stock_name} and running {n_replays:,} replays…").classes(
                "text-gray-500 text-center w-full"
            )
        run_btn.disable()
        loop = asyncio.get_event_loop()
        try:
            candles = await loop.run_in_executor(None, lambda: fetch_stock_candles_history(sid, interval=5, days=60))
            if candles is None or candles.empty:
                raise ReplayError("Dhan returned no 5-minute bars. Check the API token in .env, or try again.")
            result = await loop.run_in_executor(
                None, lambda: run_replay(candles, plan, now_ist().date(), replays=n_replays, seed=seed)
            )
        except ReplayError as e:
            _show_error(f"{stock_name}: {e}")
            return
        except Exception as e:
            _show_error(f"Replay failed: {e}")
            return
        finally:
            run_btn.enable()

        if results.client._deleted:
            return
        _render_result(stock_name, plan, result)

    def _render_result(stock_name, plan: Plan, r):
        side = "BUY" if plan.is_buy else "SELL"
        exit_label = r.exit_time
        h = r.history
        results.clear()
        with results:
            ui.html(f'<div class="rp-verdict">{r.verdict}</div>')
            for note in r.notes:
                ui.label(note).classes("rp-note")

            ui.html(f"""
            <div class="rp-tiles" style="margin-top:12px;">
              <div class="rp-tile"><div class="rp-tile-k"><span class="rp-swatch" style="background:{_TARGET}"></span>Target first</div>
                <div class="rp-tile-v">{r.target_pct}%</div><div class="rp-tile-s">₹{plan.target:.2f} · {plan.reward_r:.2f}R</div></div>
              <div class="rp-tile"><div class="rp-tile-k"><span class="rp-swatch" style="background:{_STOP}"></span>Stop first</div>
                <div class="rp-tile-v">{r.stop_pct}%</div><div class="rp-tile-s">₹{plan.stop:.2f} · −1R</div></div>
              <div class="rp-tile"><div class="rp-tile-k">Neither</div>
                <div class="rp-tile-v">{r.neither_pct}%</div><div class="rp-tile-s">still open at {exit_label}</div></div>
              <div class="rp-tile"><div class="rp-tile-k">Average R</div>
                <div class="rp-tile-v">{r.avg_r:+.3f}</div><div class="rp-tile-s">green {r.green_pct}%</div></div>
            </div>
            """)

            ui.label(
                f"{stock_name} {side} @ ₹{plan.entry:.2f} from {plan.entry_time.strftime('%H:%M')} · "
                f"price at {exit_label}: median ₹{r.close_median:.2f}, 90% of replays between "
                f"₹{r.close_p5:.2f} and ₹{r.close_p95:.2f}"
            ).classes("text-sm mt-4")
            ui.label(
                "Simulated price after each 5-minute bar. Paths keep running after a stop or target, "
                "so the bands show where price went, not open trades."
            ).classes("rp-note mb-1")
            ui.plotly(_fan_chart(r, plan)).classes("w-full")

            ui.label(
                f"Same trade on the {h['sessions']} real past sessions (entry at the {plan.entry_time.strftime('%H:%M')} "
                f"close, same % stop and target): {h['target']} target, {h['stop']} stop, {h['neither']} neither · "
                f"average R {h['avg_r']:+.3f}"
            ).classes("text-sm mt-2")

            with ui.expansion("Show the numbers", icon="table_rows").classes("w-full mt-2").props("dense"):
                ui.table(
                    columns=[{"name": k, "label": l, "field": k, "align": "right" if k != "time" else "left"}
                             for k, l in (("time", "Bar close"), ("p5", "5%"), ("p25", "25%"),
                                          ("p50", "Median"), ("p75", "75%"), ("p95", "95%"))],
                    rows=r.bands, row_key="time",
                ).props("dense flat").classes("w-full")

            ui.html(
                f'<div class="rp-foot" style="margin-top:10px;">'
                f'{r.replays:,} replays · seed {r.seed} · pool: {r.sessions} full sessions '
                f'{r.first_session} → {r.last_session} · bars drawn from the same time of day ±10 min · '
                f'a bar touching both stop and target counts as the stop · a gap through the stop counts as −1R '
                f'(a real fill can be worse). With ~{r.sessions} sessions the odds can swing by several points '
                f'from sample to sample. Built from past bars: earnings, news and halts can do what those days never did.'
                f'</div>'
            )

    run_btn.on_click(_run)

    async def _reload_signals():
        """Re-read today's open signals. Runs on page visit and every time the dropdown opens,
        since the engine finds new signals every 2 minutes while the page stays open."""
        nonlocal signals, stocks, name_to_sid
        latest = _stock_options()  # top stocks change during the day
        if latest != stocks:
            stocks, name_to_sid = latest, {v: k for k, v in latest.items()}
            stock_select.set_options(stocks, value=stock_select.value if stock_select.value in stocks else first_sid)
        signals = await asyncio.get_event_loop().run_in_executor(None, _live_signals, name_to_sid)
        if signal_select.client._deleted:
            return
        signal_select.set_options(list(signals.keys()))
        if signal_select.value not in signals:
            signal_select.set_value(None)
        placeholder = (
            f"{len(signals)} open live signal{'s' if len(signals) != 1 else ''} — pick one, or enter a plan below"
            if signals else
            "No open live signals today"
        )
        signal_select.props(f'placeholder="{placeholder}"')

    signal_select.on("popup-show", _reload_signals)

    async def refresh():
        await _reload_signals()

    return refresh
