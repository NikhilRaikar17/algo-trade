"""
Dashboard page: clocks (IST / CEST) and market price cards.
"""

import time
import asyncio
from datetime import datetime
import pandas as pd
from nicegui import ui, context

from config import now_ist, now_cest, INDICES
from state import _cache_get, _cache_set
from data import get_expiries, fetch_option_chain, fetch_option_chain_raw, fetch_5min_candles, _fetch_any_index_candles, _candles_to_daily_change
from tv_charts import render_tv_simple_candle_chart


def _compute_synthetic_futures(spot, df, strike_step):
    """Compute synthetic futures price from ATM CE and PE using put-call parity."""
    if df is None or df.empty or spot is None:
        return None
    atm = round(spot / strike_step) * strike_step
    ce_rows = df[(df["Strike"] == atm) & (df["Type"] == "CE")]
    pe_rows = df[(df["Strike"] == atm) & (df["Type"] == "PE")]
    if ce_rows.empty or pe_rows.empty:
        return None
    ce_ltp = ce_rows.iloc[0]["LTP"]
    pe_ltp = pe_rows.iloc[0]["LTP"]
    return round(atm + ce_ltp - pe_ltp, 2)


def fetch_dashboard_prices():
    """Fetch spot and synthetic futures prices for NIFTY and BANKNIFTY."""
    cache_key = "dashboard_prices"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    prices = {}
    for name, cfg in INDICES.items():
        scrip = cfg["scrip"]
        segment = cfg["segment"]
        strike_step = cfg["strike_step"]
        try:
            expiries = get_expiries(scrip, segment, 1)
            expiry = expiries[0]
            spot, df = fetch_option_chain(scrip, segment, expiry)
            fut = _compute_synthetic_futures(spot, df, strike_step)
            candles = _fetch_any_index_candles(str(scrip))
            day_stats = _candles_to_daily_change(candles) if candles is not None and not candles.empty else None
            spot_change = day_stats["change"] if day_stats else None
            spot_change_pct = day_stats["change_pct"] if day_stats else None
            prices[name] = {"spot": spot, "fut": fut, "expiry": expiry,
                            "spot_change": spot_change, "spot_change_pct": spot_change_pct}
        except Exception as e:
            print(f"  [dashboard] {name} price error: {e}")
            prices[name] = {"spot": None, "fut": None, "expiry": None,
                            "spot_change": None, "spot_change_pct": None}
        time.sleep(1)

    _cache_set(cache_key, prices)
    return prices


def fetch_atm_candles():
    """Fetch today's 5-min candles for ATM CE and PE for each index."""
    cache_key = "dashboard_atm_candles"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    today = now_ist().date()
    result = {}
    for name, cfg in INDICES.items():
        result[name] = {}
        try:
            expiries = get_expiries(cfg["scrip"], cfg["segment"], 1)
            expiry = expiries[0]
            raw = fetch_option_chain_raw(cfg["scrip"], cfg["segment"], expiry)
            spot = round(float(raw["last_price"]), 2)
            atm = round(spot / cfg["strike_step"]) * cfg["strike_step"]
            strikes = sorted(raw["oc"].keys(), key=lambda s: abs(float(s) - atm))
            sides = raw["oc"][strikes[0]] if strikes else {}
            for opt_type, key in [("CE", "ce"), ("PE", "pe")]:
                sec_id = sides.get(key, {}).get("security_id")
                if not sec_id:
                    continue
                try:
                    candles = fetch_5min_candles(sec_id)
                    if not candles.empty:
                        candles = candles[candles["timestamp"].dt.date == today].reset_index(drop=True)
                    result[name][opt_type] = {"atm": atm, "candles": candles, "expiry": expiry}
                except Exception:
                    pass
                time.sleep(0.3)
        except Exception as e:
            print(f"  [dashboard] {name} ATM candles error: {e}")
        time.sleep(0.5)

    _cache_set(cache_key, result)
    return result


def render_dashboard(container):
    """Build the dashboard page with clocks and price cards."""
    with container:
        # ---- Time Cards ----
        with ui.row().classes("w-full gap-4 sm:gap-6 mb-6 sm:mb-8 flex-wrap"):
            # IST Clock
            with ui.card().classes("flex-1 min-w-[200px] clock-card-ist !rounded-2xl"):
                with ui.column().classes("items-center w-full py-5 px-4 gap-0"):
                    ui.label("🇮🇳  INDIA").classes("clock-country-label")
                    ui.html('<canvas id="clock-ist" width="160" height="160" style="margin:8px 0 4px 0;display:block;"></canvas>')
                    ist_time_label = ui.label(now_ist().strftime("%H:%M:%S")).classes("clock-time")
                    ist_date_label = ui.label(now_ist().strftime("%a, %d %b %Y")).classes("clock-date")
                    ui.label("IST · UTC+5:30").classes("clock-tz-badge-ist")

            # CEST Clock
            with ui.card().classes("flex-1 min-w-[200px] clock-card-cest !rounded-2xl"):
                with ui.column().classes("items-center w-full py-5 px-4 gap-0"):
                    ui.label("🇪🇺  EUROPE").classes("clock-country-label")
                    ui.html('<canvas id="clock-cest" width="160" height="160" style="margin:8px 0 4px 0;display:block;"></canvas>')
                    cest_time_label = ui.label(now_cest().strftime("%H:%M:%S")).classes("clock-time")
                    cest_date_label = ui.label(now_cest().strftime("%a, %d %b %Y")).classes("clock-date")
                    ui.label("CET/CEST · UTC+1/+2").classes("clock-tz-badge-cest")

        # Inject analog clock JS — runs entirely client-side, no server round-trips
        ui.add_body_html("""
<script>
(function() {
  function drawClock(canvasId, offsetTotalMinutes) {
    var canvas = document.getElementById(canvasId);
    if (!canvas) return;
    var ctx = canvas.getContext('2d');
    var now = new Date();
    var utc = now.getTime() + now.getTimezoneOffset() * 60000;
    var local = new Date(utc + offsetTotalMinutes * 60000);
    var h = local.getHours() % 12;
    var m = local.getMinutes();
    var s = local.getSeconds();
    var ms = local.getMilliseconds();

    var cx = 80, cy = 80, r = 72;
    ctx.clearRect(0, 0, 160, 160);

    // Face
    ctx.beginPath();
    ctx.arc(cx, cy, r, 0, 2*Math.PI);
    ctx.fillStyle = '#f8fafc';
    ctx.fill();
    ctx.strokeStyle = '#e2e8f0';
    ctx.lineWidth = 2;
    ctx.stroke();

    // Hour ticks
    for (var i = 0; i < 12; i++) {
      var ang = (i / 12) * 2 * Math.PI - Math.PI/2;
      var inner = i % 3 === 0 ? r - 14 : r - 9;
      ctx.beginPath();
      ctx.moveTo(cx + Math.cos(ang) * inner, cy + Math.sin(ang) * inner);
      ctx.lineTo(cx + Math.cos(ang) * (r - 3), cy + Math.sin(ang) * (r - 3));
      ctx.strokeStyle = i % 3 === 0 ? '#64748b' : '#cbd5e1';
      ctx.lineWidth = i % 3 === 0 ? 2.5 : 1.2;
      ctx.stroke();
    }

    // Hour hand
    var hAngle = ((h + m/60 + s/3600) / 12) * 2 * Math.PI - Math.PI/2;
    ctx.beginPath();
    ctx.moveTo(cx, cy);
    ctx.lineTo(cx + Math.cos(hAngle) * (r * 0.52), cy + Math.sin(hAngle) * (r * 0.52));
    ctx.strokeStyle = '#0f172a';
    ctx.lineWidth = 4;
    ctx.lineCap = 'round';
    ctx.stroke();

    // Minute hand
    var mAngle = ((m + s/60) / 60) * 2 * Math.PI - Math.PI/2;
    ctx.beginPath();
    ctx.moveTo(cx, cy);
    ctx.lineTo(cx + Math.cos(mAngle) * (r * 0.72), cy + Math.sin(mAngle) * (r * 0.72));
    ctx.strokeStyle = '#334155';
    ctx.lineWidth = 2.5;
    ctx.lineCap = 'round';
    ctx.stroke();

    // Second hand
    var sAngle = ((s + ms/1000) / 60) * 2 * Math.PI - Math.PI/2;
    ctx.beginPath();
    ctx.moveTo(cx - Math.cos(sAngle) * 14, cy - Math.sin(sAngle) * 14);
    ctx.lineTo(cx + Math.cos(sAngle) * (r * 0.82), cy + Math.sin(sAngle) * (r * 0.82));
    ctx.strokeStyle = '#ef4444';
    ctx.lineWidth = 1.5;
    ctx.lineCap = 'round';
    ctx.stroke();

    // Center dot
    ctx.beginPath();
    ctx.arc(cx, cy, 4, 0, 2*Math.PI);
    ctx.fillStyle = '#ef4444';
    ctx.fill();
    ctx.beginPath();
    ctx.arc(cx, cy, 2, 0, 2*Math.PI);
    ctx.fillStyle = '#fff';
    ctx.fill();
  }

  function getCestOffsetMinutes() {
    // Determine if currently CEST (+120) or CET (+60) based on UTC date
    var now = new Date();
    var jan = new Date(now.getFullYear(), 0, 1);
    var jul = new Date(now.getFullYear(), 6, 1);
    // Europe/Berlin: CEST (UTC+2) late-Mar to late-Oct
    var janOffset = jan.getTimezoneOffset();
    var julOffset = jul.getTimezoneOffset();
    var stdOffset = Math.max(janOffset, julOffset); // larger = less positive = winter
    // Simple DST: if today is between last Sunday Mar and last Sunday Oct → CEST
    var y = now.getFullYear();
    function lastSunday(month) {
      var d = new Date(y, month + 1, 0); // last day of month
      d.setDate(d.getDate() - d.getDay());
      return d;
    }
    var dstStart = lastSunday(2); dstStart.setHours(1);  // last Sun March 1am UTC
    var dstEnd   = lastSunday(9); dstEnd.setHours(1);    // last Sun October 1am UTC
    var utcNow = new Date(now.getTime() + now.getTimezoneOffset() * 60000);
    return (utcNow >= dstStart && utcNow < dstEnd) ? 120 : 60;
  }

  function tickClocks() {
    drawClock('clock-ist',  330);                   // IST = UTC+5:30 = +330 min
    drawClock('clock-cest', getCestOffsetMinutes()); // CET+1 or CEST+2
    requestAnimationFrame(tickClocks);
  }

  // Wait for DOM then start
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', tickClocks);
  } else {
    tickClocks();
  }
})();
</script>
""")

        # Update digital time labels every second from server
        def update_clocks():
            ist_now = now_ist()
            cest_now = now_cest()
            ist_time_label.set_text(ist_now.strftime("%H:%M:%S"))
            ist_date_label.set_text(ist_now.strftime("%a, %d %b %Y"))
            cest_time_label.set_text(cest_now.strftime("%H:%M:%S"))
            cest_date_label.set_text(cest_now.strftime("%a, %d %b %Y"))

        ui.timer(1, update_clocks)

        # ---- API Status Card ----
        api_status_container = ui.element("div").classes("w-full mb-6")
        with api_status_container:
            _render_api_status_loading()

        # ---- Section Header ----
        with ui.row().classes("w-full items-center mb-4"):
            with ui.row().classes("items-center gap-2"):
                ui.icon("monitoring", size="22px").classes("text-blue-500")
                ui.label("Market Overview").classes(
                    "text-lg font-semibold text-gray-800"
                )
            ui.space()
            update_time_label = ui.label("").classes("text-xs text-gray-400")

        # ---- Price Cards ----
        price_container = ui.element("div").classes("w-full")

        # Loading state
        with price_container:
            with ui.element("div").classes("w-full responsive-price-grid"):
                for name in ["NIFTY", "BANKNIFTY"]:
                    card_cls = "price-card-nifty" if name == "NIFTY" else "price-card-bnf"
                    for ptype in ["SPOT", "FUT"]:
                        with ui.card().classes(
                            f"{card_cls} border border-gray-200 shadow-sm !rounded-xl"
                        ).style("min-height: 120px"):
                            with ui.column().classes("items-center justify-center w-full h-full py-4"):
                                ui.label(f"{name} {ptype}").classes(
                                    "text-xs font-semibold text-gray-400 uppercase tracking-wider"
                                )
                                ui.label("--").classes(
                                    "text-2xl font-bold text-gray-300 mt-1"
                                )

        # ---- ATM Option Charts ----
        charts_container = ui.element("div").classes("w-full mt-6")

    page_client = context.client

    async def refresh():
        prices = await asyncio.get_event_loop().run_in_executor(
            None, fetch_dashboard_prices
        )
        if page_client._deleted:
            return

        # Derive API health from price fetch result — no extra API call needed
        any_ok = any(v.get("spot") is not None for v in prices.values())
        api_health = {"ok": any_ok, "latency_ms": None, "error": None if any_ok else "Could not fetch price data"}
        api_status_container.clear()
        with api_status_container:
            _render_api_status(api_health)

        price_container.clear()
        with price_container:
            with ui.element("div").classes("w-full responsive-price-grid"):
                for name in ["NIFTY", "BANKNIFTY"]:
                    data = prices.get(name, {})
                    spot = data.get("spot")
                    fut = data.get("fut")
                    expiry = data.get("expiry")
                    spot_change = data.get("spot_change")
                    spot_change_pct = data.get("spot_change_pct")

                    card_cls = "price-card-nifty" if name == "NIFTY" else "price-card-bnf"
                    dot_color = "bg-sky-500" if name == "NIFTY" else "bg-violet-500"

                    if spot_change is None:
                        side_border_color = "#d1d5db"  # gray-300
                    elif spot_change >= 0:
                        side_border_color = "#4ade80"  # green-400
                    else:
                        side_border_color = "#f87171"  # red-400

                    # Spot card
                    with ui.card().classes(
                        f"{card_cls} shadow-sm !rounded-xl"
                    ).style(f"min-height: 120px; border: 2px solid {side_border_color} !important;"):
                        with ui.column().classes("w-full h-full justify-center py-4 sm:py-5 pl-4 sm:pl-5"):
                            with ui.row().classes("items-center gap-2"):
                                ui.element("div").classes(f"w-2 h-2 rounded-full {dot_color}")
                                ui.label(f"{name} SPOT").classes(
                                    "text-[11px] font-bold text-gray-500 uppercase tracking-widest"
                                )
                            spot_text = f"{spot:,.2f}" if spot else "N/A"
                            ui.label(spot_text).classes(
                                "text-xl sm:text-3xl font-bold text-gray-900 mt-2 tracking-tight"
                            )
                            if spot_change is not None and spot_change_pct is not None:
                                sign = "+" if spot_change >= 0 else ""
                                if spot_change >= 0:
                                    bg = "bg-green-50 text-green-700"
                                    icon = "arrow_drop_up"
                                else:
                                    bg = "bg-red-50 text-red-700"
                                    icon = "arrow_drop_down"
                                with ui.row().classes(
                                    f"items-center gap-0 mt-2 px-2 py-0.5 rounded-md {bg}"
                                ).style("width: fit-content"):
                                    ui.icon(icon, size="18px")
                                    ui.label(
                                        f"{sign}{spot_change:,.2f} ({sign}{spot_change_pct}%)"
                                    ).classes("text-xs font-semibold")

                    # Futures card
                    with ui.card().classes(
                        f"{card_cls} shadow-sm !rounded-xl"
                    ).style(f"min-height: 120px; border: 2px solid {side_border_color} !important;"):
                        with ui.column().classes("w-full h-full justify-center py-4 sm:py-5 pl-4 sm:pl-5"):
                            with ui.row().classes("items-center gap-2"):
                                ui.element("div").classes(f"w-2 h-2 rounded-full {dot_color}")
                                exp_tag = ""
                                if expiry:
                                    exp_date = datetime.strptime(expiry, "%Y-%m-%d")
                                    exp_tag = f" ({exp_date.strftime('%d%b').upper()})"
                                ui.label(f"{name} FUT{exp_tag}").classes(
                                    "text-[11px] font-bold text-gray-500 uppercase tracking-widest"
                                )
                            fut_text = f"{fut:,.2f}" if fut else "N/A"
                            ui.label(fut_text).classes(
                                "text-xl sm:text-3xl font-bold text-gray-900 mt-2 tracking-tight"
                            )

                            # Basis
                            if spot and fut:
                                basis = round(fut - spot, 2)
                                basis_pct = round((basis / spot) * 100, 3)
                                sign = "+" if basis >= 0 else ""
                                if basis >= 0:
                                    bg = "bg-green-50 text-green-700"
                                    icon = "arrow_drop_up"
                                else:
                                    bg = "bg-red-50 text-red-700"
                                    icon = "arrow_drop_down"
                                with ui.row().classes(
                                    f"items-center gap-0 mt-2 px-2 py-0.5 rounded-md {bg}"
                                ).style("width: fit-content"):
                                    ui.icon(icon, size="18px")
                                    ui.label(
                                        f"{sign}{basis:,.2f} ({sign}{basis_pct}%)"
                                    ).classes("text-xs font-semibold")

        update_time_label.set_text(
            f"Updated {now_ist().strftime('%H:%M:%S')} IST"
        )

        # ---- ATM Option Charts ----
        atm_candles = await asyncio.get_event_loop().run_in_executor(
            None, fetch_atm_candles
        )
        if page_client._deleted:
            return

        charts_container.clear()
        with charts_container:
            with ui.row().classes("items-center gap-2 mb-4"):
                ui.icon("candlestick_chart", size="22px").classes("text-blue-500")
                ui.label("ATM Option Charts (5-min)").classes("text-lg font-semibold text-gray-800")

            for name in ["NIFTY", "BANKNIFTY"]:
                index_data = atm_candles.get(name, {})
                if not index_data:
                    continue

                # Use CE data to get atm/expiry (same for both legs)
                sample = index_data.get("CE") or index_data.get("PE")
                if not sample:
                    continue
                atm = sample["atm"]
                expiry = sample["expiry"]
                exp_tag = datetime.strptime(expiry, "%Y-%m-%d").strftime("%d%b").upper()

                with ui.card().classes("w-full border border-gray-200 shadow-sm !rounded-xl mb-4 p-4"):
                    with ui.row().classes("items-center gap-3 mb-3"):
                        dot_color = "bg-sky-500" if name == "NIFTY" else "bg-violet-500"
                        ui.element("div").classes(f"w-3 h-3 rounded-full {dot_color}")
                        ui.label(f"{name} — ATM {int(atm)} ({exp_tag})").classes(
                            "text-base font-bold text-gray-800"
                        )

                    for opt_type in ["CE", "PE"]:
                        label_cls = "text-green-700 font-bold" if opt_type == "CE" else "text-red-700 font-bold"
                        ui.label(f"{opt_type} {int(atm)}").classes(f"text-sm {label_cls} mt-3 mb-1")
                        entry = index_data.get(opt_type)
                        if entry is None:
                            ui.label(f"No data for {opt_type}").classes("text-orange-500 italic")
                            continue
                        candles = entry["candles"]
                        if candles is None or candles.empty:
                            ui.label(f"No candle data yet for {opt_type} today.").classes("text-gray-400 italic")
                            continue
                        ltp = round(float(candles["close"].iloc[-1]), 2)
                        ui.label(f"LTP: {ltp:,.2f} | {len(candles)} candles today").classes(
                            "text-xs text-gray-500 mb-2"
                        )
                        render_tv_simple_candle_chart(candles, height=300)

    return refresh


def _render_api_status_loading():
    with ui.card().classes(
        "w-full border border-gray-100 rounded-xl shadow-sm bg-white px-5 py-3"
    ).props("flat"):
        with ui.row().classes("items-center gap-3"):
            ui.spinner("dots", size="sm").classes("text-gray-400")
            ui.label("Checking Dhan API…").classes("text-sm text-gray-400")


def _render_api_status(h):
    if h["ok"]:
        border = "border-green-200"
        bg     = "bg-green-50"
        dot    = "bg-green-500"
        title  = "Dhan API — Connected"
        title_cls = "text-sm font-semibold text-green-700"
        detail = f"Latency: {h['latency_ms']} ms" if h["latency_ms"] else "Price data fetched successfully"
        detail_cls = "text-xs text-green-600"
        icon   = "check_circle"
        icon_cls = "text-green-500"
    else:
        border = "border-red-200"
        bg     = "bg-red-50"
        dot    = "bg-red-500"
        title  = "Dhan API — Unreachable"
        title_cls = "text-sm font-semibold text-red-700"
        detail = h["error"] or "Unknown error"
        detail_cls = "text-xs text-red-500"
        icon   = "error_outline"
        icon_cls = "text-red-500"

    with ui.card().classes(
        f"w-full border {border} {bg} rounded-xl shadow-sm px-5 py-3"
    ).props("flat"):
        with ui.row().classes("items-center gap-3 w-full"):
            ui.icon(icon, size="22px").classes(icon_cls)
            with ui.column().classes("gap-0"):
                ui.label(title).classes(title_cls)
                ui.label(detail).classes(detail_cls)
            ui.space()
            with ui.element("div").classes(
                f"flex items-center gap-1.5 text-xs font-medium {'text-green-600' if h['ok'] else 'text-red-600'}"
            ):
                ui.element("div").classes(
                    f"w-2 h-2 rounded-full {dot} {'animate-pulse' if not h['ok'] else ''}"
                )
                ui.label("Live" if h["ok"] else "Down")
