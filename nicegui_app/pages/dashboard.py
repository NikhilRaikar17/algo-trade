"""
Dashboard page: clocks (IST / CEST) and market price cards.
"""

import time
import asyncio
from nicegui import ui, context

from config import now_ist, now_cest, INDICES
from state import _cache_get, _cache_set, get_live_price, get_ws_connected, get_all_global_prices
from data import get_expiries, fetch_option_chain, _fetch_any_index_candles, _candles_to_daily_change


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

        # ---- API Connection Status Card ----
        with ui.card().classes(
            "w-full mb-6 !rounded-2xl shadow-sm border border-gray-100"
        ).style("background: linear-gradient(135deg, #f8fafc 0%, #f1f5f9 100%);").props("flat"):
            with ui.row().classes("items-center gap-4 px-5 py-4 flex-wrap"):
                # Section label
                with ui.row().classes("items-center gap-2 mr-2"):
                    ui.icon("hub", size="20px").classes("text-slate-500")
                    ui.label("API Connection").classes("text-sm font-semibold text-slate-600 uppercase tracking-wider")

                ui.element("div").classes("w-px h-6 bg-gray-200")

                # REST API status badge (updated after fetch_dashboard_prices succeeds/fails)
                with ui.row().classes("items-center gap-2"):
                    _api_dot = ui.element("div").classes("w-2.5 h-2.5 rounded-full bg-gray-300")
                    _api_icon = ui.icon("cloud_queue", size="18px").classes("text-gray-400")
                    _api_label = ui.label("Dhan API · Checking…").classes("text-sm font-semibold text-gray-500")

                ui.element("div").classes("w-px h-6 bg-gray-200")

                # WS status badge
                with ui.row().classes("items-center gap-2"):
                    _ws_dot = ui.element("div").classes("w-2.5 h-2.5 rounded-full bg-red-500 animate-pulse")
                    _ws_icon = ui.icon("wifi_off", size="18px").classes("text-red-500")
                    _ws_label = ui.label("Live Data · Disconnected").classes("text-sm font-semibold text-red-600")

                ui.element("div").classes("w-px h-6 bg-gray-200")

                # Last tick
                with ui.row().classes("items-center gap-2"):
                    ui.icon("schedule", size="18px").classes("text-gray-400")
                    _tick_label = ui.label("Waiting for first tick…").classes("text-sm text-gray-500")

        # ---- Section Header ----
        with ui.row().classes("w-full items-center mb-4"):
            with ui.row().classes("items-center gap-2"):
                ui.icon("monitoring", size="22px").classes("text-emerald-500")
                ui.label("Market Overview").classes("text-lg font-semibold text-gray-800")
            ui.space()
            update_time_label = ui.label("").classes("text-xs text-gray-400")

        # ---- Price Cards (created ONCE; labels updated in-place) ----
        _price_labels: dict[str, dict] = {}  # key → {"price": label, "badge": label, "card": card}
        with ui.element("div").classes("w-full responsive-price-grid"):
            for name in ["NIFTY", "BANKNIFTY"]:
                card_cls = "price-card-nifty" if name == "NIFTY" else "price-card-bnf"
                dot_color = "bg-emerald-500" if name == "NIFTY" else "bg-teal-600"
                for ptype in ["SPOT", "FUT"]:
                    key = f"{name}_{ptype}"
                    with ui.card().classes(
                        f"{card_cls} shadow-sm !rounded-xl"
                    ).style("min-height: 120px; border: 2px solid #d1d5db !important;") as card:
                        with ui.column().classes("w-full h-full justify-center py-4 sm:py-5 pl-4 sm:pl-5"):
                            with ui.row().classes("items-center gap-2"):
                                ui.element("div").classes(f"w-2 h-2 rounded-full {dot_color}")
                                label_text = f"{name} {ptype}"
                                ui.label(label_text).classes(
                                    "text-[11px] font-bold text-gray-500 uppercase tracking-widest"
                                )
                            price_lbl = ui.label("--").classes(
                                "text-xl sm:text-3xl font-bold text-gray-900 mt-2 tracking-tight"
                            )
                            badge_lbl = ui.label("").classes("text-xs font-semibold mt-2")
                    _price_labels[key] = {"price": price_lbl, "badge": badge_lbl, "card": card}

        def _update_price_labels():
            """Update price labels in-place every 2s.

            Priority:
            - Market hours: use live WS price from state._live_prices
            - After hours / WS unavailable: fall back to REST spot price from
              the dashboard_prices cache (populated by fetch_dashboard_prices)
            """
            import state as _state
            from state import _cache_get
            rest_prices = _cache_get("dashboard_prices") or {}

            for name in ["NIFTY", "BANKNIFTY"]:
                ws_entry = _state.get_live_price(name)
                spot_key = f"{name}_SPOT"
                if spot_key not in _price_labels:
                    continue

                if ws_entry is not None:
                    # Live WS data available — use it
                    ltp = ws_entry["ltp"]
                    change = ws_entry["change"]
                    change_pct = ws_entry["change_pct"]
                    sign = "+" if change >= 0 else ""
                    color_cls = "text-green-700" if change >= 0 else "text-red-700"
                    _price_labels[spot_key]["price"].set_text(f"{ltp:,.2f}")
                    _price_labels[spot_key]["badge"].set_text(
                        f"{sign}{change:,.2f} ({sign}{change_pct}%)"
                    )
                    _price_labels[spot_key]["badge"].classes(color_cls, remove="text-green-700 text-red-700")
                else:
                    # No WS data — fall back to REST spot price (after-hours LTP)
                    rest_entry = rest_prices.get(name, {})
                    spot = rest_entry.get("spot")
                    if spot is not None:
                        spot_change = rest_entry.get("spot_change")
                        spot_change_pct = rest_entry.get("spot_change_pct")
                        _price_labels[spot_key]["price"].set_text(f"{spot:,.2f}")
                        if spot_change is not None and spot_change_pct is not None:
                            sign = "+" if spot_change >= 0 else ""
                            color_cls = "text-green-700" if spot_change >= 0 else "text-red-700"
                            _price_labels[spot_key]["badge"].set_text(
                                f"{sign}{spot_change:,.2f} ({sign}{spot_change_pct}%)"
                            )
                            _price_labels[spot_key]["badge"].classes(color_cls, remove="text-green-700 text-red-700")

            # Update API status pills in-place
            last_tick_times = [
                entry.get("timestamp")
                for key in ["NIFTY", "BANKNIFTY", "VIX"]
                for entry in [_state.get_live_price(key)]
                if entry and entry.get("timestamp")
            ]
            last_tick = max(last_tick_times) if last_tick_times else None
            ws_ok = _state.get_ws_connected()
            if ws_ok:
                _ws_icon.props("name=wifi").classes("text-green-500", remove="text-red-500")
                _ws_label.set_text("Live Data · Connected")
                _ws_label.classes("text-green-600 font-semibold", remove="text-red-600")
                _ws_dot.classes("bg-green-500", remove="bg-red-500 animate-pulse")
            else:
                _ws_icon.props("name=wifi_off").classes("text-red-500", remove="text-green-500")
                _ws_label.set_text("Live Data · Disconnected")
                _ws_label.classes("text-red-600 font-semibold", remove="text-green-600")
                _ws_dot.classes("bg-red-500 animate-pulse", remove="bg-green-500")
            tick_text = f"Last tick: {last_tick} IST" if last_tick else "Waiting for first tick…"
            _tick_label.set_text(tick_text)

        # Timer runs regardless of tab visibility — set_text on hidden labels is harmless
        # and cheaper than recreating the timer on each navigation.
        ui.timer(2, _update_price_labels)

        # ---- Widgets Row ----
        widgets_container = ui.element("div").classes("w-full mt-8")
        with widgets_container:
            _render_widgets_loading()

    page_client = context.client

    async def refresh():
        prices = await asyncio.get_running_loop().run_in_executor(
            None, fetch_dashboard_prices
        )
        if page_client._deleted:
            return

        # Update REST API status indicator
        api_ok = any(v.get("spot") is not None for v in prices.values())
        if api_ok:
            _api_dot.classes("bg-green-500", remove="bg-red-500 bg-gray-300 animate-pulse")
            _api_icon.props("name=cloud_done").classes("text-green-500", remove="text-red-500 text-gray-400")
            _api_label.set_text("Dhan API · Connected")
            _api_label.classes("text-green-600", remove="text-red-600 text-gray-500")
        else:
            _api_dot.classes("bg-red-500 animate-pulse", remove="bg-green-500 bg-gray-300")
            _api_icon.props("name=cloud_off").classes("text-red-500", remove="text-green-500 text-gray-400")
            _api_label.set_text("Dhan API · Error")
            _api_label.classes("text-red-600", remove="text-green-600 text-gray-500")

        # Update FUT card labels in-place
        for name in ["NIFTY", "BANKNIFTY"]:
            data = prices.get(name, {})
            spot = data.get("spot")
            fut = data.get("fut")

            fut_key = f"{name}_FUT"
            if fut_key in _price_labels and fut is not None:
                _price_labels[fut_key]["price"].set_text(f"{fut:,.2f}")
                if spot and fut:
                    basis = round(fut - spot, 2)
                    basis_pct = round((basis / spot) * 100, 3)
                    sign = "+" if basis >= 0 else ""
                    badge_text = f"{sign}{basis:,.2f} ({sign}{basis_pct}%)"
                    color_cls = "text-green-700" if basis >= 0 else "text-red-700"
                    _price_labels[fut_key]["badge"].set_text(badge_text)
                    _price_labels[fut_key]["badge"].classes(color_cls, remove="text-green-700 text-red-700")

        update_time_label.set_text(
            f"Updated {now_ist().strftime('%H:%M:%S')} IST"
        )

        # ---- Widgets ----
        nifty_candles = await asyncio.get_running_loop().run_in_executor(
            None, lambda: _fetch_any_index_candles("13")
        )
        rsi_value = None
        if nifty_candles is not None and not nifty_candles.empty and "close" in nifty_candles.columns:
            closes = [float(c) for c in nifty_candles["close"].tolist()]
            rsi_value = _compute_rsi14(closes)

        vix_entry = get_live_price("VIX")
        vix_value = vix_entry["ltp"] if vix_entry else None
        global_snapshot = get_all_global_prices()

        if page_client._deleted:
            return

        widgets_container.clear()
        with widgets_container:
            with ui.row().classes("items-center gap-2 mb-4"):
                ui.icon("insights", size="22px").classes("text-emerald-500")
                ui.label("Market Insights").classes("text-lg font-semibold text-gray-800")
            with ui.element("div").classes("w-full widgets-grid"):
                _render_sentiment_gauge(rsi_value)
                _render_vix_dial(vix_value)
                _render_top_movers(global_snapshot)
                _render_economic_calendar()

    return refresh


def _compute_rsi14(closes: list[float]) -> float | None:
    """Approximate RSI(14) using simple moving average of last 14 gains/losses.

    Note: Uses SMA rather than Wilder's EMA, so values may differ slightly from
    ta-lib or charting platforms for short series. Sufficient for the sentiment gauge.
    Returns None if fewer than 15 data points.
    """
    if len(closes) < 15:
        return None
    gains, losses = [], []
    for i in range(1, len(closes)):
        delta = closes[i] - closes[i - 1]
        gains.append(max(delta, 0))
        losses.append(max(-delta, 0))
    avg_gain = sum(gains[-14:]) / 14
    avg_loss = sum(losses[-14:]) / 14
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 2)



def _render_global_markets_loading():
    with ui.card().classes("w-full border border-gray-100 rounded-xl shadow-sm bg-white px-5 py-3").props("flat"):
        with ui.row().classes("items-center gap-3"):
            ui.spinner("dots", size="sm").classes("text-gray-400")
            ui.label("Loading global markets…").classes("text-sm text-gray-400")


def _render_widgets_loading():
    with ui.card().classes("w-full border border-gray-100 rounded-xl shadow-sm bg-white px-5 py-3").props("flat"):
        with ui.row().classes("items-center gap-3"):
            ui.spinner("dots", size="sm").classes("text-gray-400")
            ui.label("Loading market insights…").classes("text-sm text-gray-400")


_GLOBAL_GROUPS = [
    ("🌎 US Indices",           ["^GSPC", "^IXIC", "^DJI"]),
    ("🌍 Europe",               ["^FTSE", "^GDAXI", "^FCHI"]),
    ("🌏 Asia",                 ["^N225", "^HSI", "000001.SS"]),
    ("⚡ Commodities & Crypto", ["GC=F", "GC=F_INR", "CL=F", "BTC-USD", "ETH-USD"]),
]


def _render_global_markets_grid(prices: dict):
    """Render global market tiles grouped by region."""
    with ui.row().classes("items-center gap-2 mb-4"):
        ui.icon("public", size="22px").classes("text-emerald-500")
        ui.label("Global Markets").classes("text-lg font-semibold text-gray-800")
        ui.space()
        with ui.element("div").classes(
            "text-xs text-gray-400 bg-gray-100 rounded-full px-3 py-0.5"
        ):
            ui.label("Delayed ~15 min")

    for group_label, symbols in _GLOBAL_GROUPS:
        ui.label(group_label).classes("text-xs font-bold text-gray-500 uppercase tracking-wider mt-4 mb-2")
        grid_cls = "global-grid-4" if len(symbols) >= 4 else "global-grid-3"
        with ui.element("div").classes(f"w-full {grid_cls}"):
            for sym in symbols:
                entry = prices.get(sym)
                if entry is None:
                    continue
                price = entry["price"]
                change_pct = entry["change_pct"]
                flag = entry["flag"]
                name = entry["name"]
                currency = entry["currency"]
                up = change_pct >= 0
                sign = "+" if up else ""
                border_color = "#4ade80" if up else "#f87171"
                badge_cls = "bg-green-50 text-green-700" if up else "bg-red-50 text-red-700"
                arrow = "arrow_drop_up" if up else "arrow_drop_down"

                with ui.card().classes("border shadow-sm !rounded-xl h-full").style(
                    f"border: 1.5px solid {border_color} !important; min-height: 95px;"
                ):
                    with ui.column().classes("w-full h-full justify-between px-3 py-3 gap-1"):
                        with ui.row().classes("items-center gap-1.5"):
                            ui.label(flag).style("font-size: 1.1rem; line-height:1;")
                            ui.label(name).classes("text-[10px] font-bold text-gray-500 uppercase tracking-wider").style("white-space:nowrap; overflow:hidden; text-overflow:ellipsis;")
                        ui.label(f"{currency} {price:,.2f}").classes("text-sm font-bold text-gray-900 leading-tight")
                        with ui.row().classes(
                            f"items-center gap-0 px-1.5 py-0.5 rounded-md {badge_cls}"
                        ).style("width: fit-content"):
                            ui.icon(arrow, size="16px")
                            ui.label(f"{sign}{change_pct}%").classes("text-xs font-semibold")


def _render_sentiment_gauge(rsi: float | None):
    """Market Sentiment: SVG arc needle driven by RSI(14)."""
    if rsi is None:
        score = 50
        label = "Neutral"
        color = "#94a3b8"
    elif rsi < 30:
        score = int(rsi * 100 / 30 * 0.2)
        label = "Extreme Fear"
        color = "#ef4444"
    elif rsi < 40:
        score = int(20 + (rsi - 30) * 2)
        label = "Fear"
        color = "#f97316"
    elif rsi < 60:
        score = int(40 + (rsi - 40))
        label = "Neutral"
        color = "#eab308"
    elif rsi < 70:
        score = int(60 + (rsi - 60) * 2)
        label = "Greed"
        color = "#22c55e"
    else:
        score = int(80 + (rsi - 70) * 100 / 30 * 0.2)
        label = "Extreme Greed"
        color = "#16a34a"

    score = max(0, min(100, score))
    angle = -90 + score * 1.8

    svg = f"""
    <svg viewBox="0 0 200 120" width="180" height="110">
      <defs>
        <linearGradient id="arcGrad" x1="0%" y1="0%" x2="100%" y2="0%">
          <stop offset="0%"   stop-color="#ef4444"/>
          <stop offset="25%"  stop-color="#f97316"/>
          <stop offset="50%"  stop-color="#eab308"/>
          <stop offset="75%"  stop-color="#22c55e"/>
          <stop offset="100%" stop-color="#16a34a"/>
        </linearGradient>
      </defs>
      <path d="M 20 100 A 80 80 0 0 1 180 100" fill="none" stroke="url(#arcGrad)" stroke-width="14" stroke-linecap="round"/>
      <path d="M 20 100 A 80 80 0 0 1 180 100" fill="none" stroke="#f1f5f9" stroke-width="5" stroke-linecap="round" opacity="0.4"/>
      <g transform="rotate({angle}, 100, 100)">
        <line x1="100" y1="100" x2="100" y2="30" stroke="#0f172a" stroke-width="3" stroke-linecap="round"/>
        <circle cx="100" cy="100" r="5" fill="#0f172a"/>
      </g>
    </svg>
    """
    with ui.card().classes("border border-gray-200 shadow-sm !rounded-xl p-4").props("flat"):
        with ui.column().classes("items-center gap-1 w-full"):
            ui.label("Market Sentiment").classes("text-xs font-bold text-gray-500 uppercase tracking-wider")
            ui.html(svg)
            ui.label(label).classes("text-sm font-bold mt-1").style(f"color: {color};")
            rsi_text = f"RSI(14): {rsi}" if rsi is not None else "Insufficient data"
            ui.label(rsi_text).classes("text-xs text-gray-400")


def _render_vix_dial(vix: float | None):
    """India VIX circular ring dial."""
    if vix is None:
        display = "--"
        ring_color = "#94a3b8"
        zone_label = "No data"
        zone_cls = "text-gray-400"
    elif vix < 15:
        display = f"{vix:.1f}"
        ring_color = "#22c55e"
        zone_label = "Calm"
        zone_cls = "text-green-600"
    elif vix < 20:
        display = f"{vix:.1f}"
        ring_color = "#eab308"
        zone_label = "Moderate"
        zone_cls = "text-yellow-600"
    else:
        display = f"{vix:.1f}"
        ring_color = "#ef4444"
        zone_label = "Elevated Fear"
        zone_cls = "text-red-600"

    max_vix = 40.0
    fill_ratio = min(float(vix or 0) / max_vix, 1.0)
    circ = 283.0
    dash_len = round(fill_ratio * circ, 1)

    svg = f"""
    <svg viewBox="0 0 120 120" width="110" height="110">
      <circle cx="60" cy="60" r="45" fill="none" stroke="#f1f5f9" stroke-width="12"/>
      <circle cx="60" cy="60" r="45" fill="none" stroke="{ring_color}" stroke-width="12"
              stroke-dasharray="{dash_len} {circ}" stroke-linecap="round"
              transform="rotate(-90 60 60)"/>
      <text x="60" y="55" text-anchor="middle" font-size="20" font-weight="700" fill="#0f172a">{display}</text>
      <text x="60" y="72" text-anchor="middle" font-size="9" fill="#94a3b8">India VIX</text>
    </svg>
    """
    with ui.card().classes("border border-gray-200 shadow-sm !rounded-xl p-4").props("flat"):
        with ui.column().classes("items-center gap-1 w-full"):
            ui.label("India VIX").classes("text-xs font-bold text-gray-500 uppercase tracking-wider")
            ui.html(svg)
            ui.label(zone_label).classes(f"text-sm font-bold {zone_cls}")


def _render_top_movers(all_prices: dict):
    """Table of biggest movers across tracked indices."""
    import state as _state
    rows = []
    for sym, entry in all_prices.items():
        rows.append({
            "name": entry["name"],
            "flag": entry["flag"],
            "price": entry["price"],
            "change_pct": entry["change_pct"],
            "currency": entry["currency"],
        })
    for idx_name in ["NIFTY", "BANKNIFTY"]:
        lp = _state.get_live_price(idx_name)
        if lp:
            rows.append({
                "name": idx_name,
                "flag": "🇮🇳",
                "price": lp["ltp"],
                "change_pct": lp["change_pct"],
                "currency": "INR",
            })

    rows.sort(key=lambda r: abs(r["change_pct"]), reverse=True)
    top5 = rows[:5]

    with ui.card().classes("border border-gray-200 shadow-sm !rounded-xl p-4").props("flat"):
        ui.label("Top Movers").classes("text-xs font-bold text-gray-500 uppercase tracking-wider mb-3")
        if not top5:
            ui.label("No data yet").classes("text-sm text-gray-400 italic")
            return
        for row in top5:
            pct = row["change_pct"]
            up = pct >= 0
            sign = "+" if up else ""
            row_bg = "bg-green-50" if up else "bg-red-50"
            pct_cls = "text-green-700 font-semibold" if up else "text-red-700 font-semibold"
            with ui.row().classes(f"w-full items-center justify-between px-2 py-1.5 rounded-lg {row_bg} mb-1"):
                with ui.row().classes("items-center gap-2"):
                    ui.label(row["flag"]).style("font-size: 0.9rem;")
                    ui.label(row["name"]).classes("text-xs font-bold text-gray-700 truncate").style("max-width: 100px;")
                ui.label(f"{sign}{pct}%").classes(pct_cls).style("font-size: 0.75rem;")


def _render_economic_calendar():
    """Upcoming economic events strip."""
    from economic_calendar import get_upcoming_events
    from datetime import date
    events = get_upcoming_events(n=5)
    today = date.today()

    type_colors = {
        "expiry": ("bg-blue-100 text-blue-700", "Expiry"),
        "rbi":    ("bg-amber-100 text-amber-700", "RBI"),
        "fed":    ("bg-purple-100 text-purple-700", "Fed"),
    }

    with ui.card().classes("border border-gray-200 shadow-sm !rounded-xl p-4").props("flat"):
        ui.label("Economic Calendar").classes("text-xs font-bold text-gray-500 uppercase tracking-wider mb-3")
        if not events:
            ui.label("No upcoming events").classes("text-sm text-gray-400 italic")
            return
        for ev in events:
            delta = (ev["date"] - today).days
            highlight = delta <= 3
            row_cls = "border-l-4 border-amber-400 bg-amber-50 pl-2" if highlight else "border-l-4 border-gray-200 pl-2"
            chip_cls, chip_label = type_colors.get(ev["type"], ("bg-gray-100 text-gray-600", ev["type"]))
            with ui.row().classes(f"w-full items-center gap-3 py-1.5 pr-2 rounded-r-lg {row_cls} mb-1"):
                with ui.element("div").classes(
                    "text-xs font-bold text-gray-500 bg-white border border-gray-200 rounded-lg px-2 py-1 text-center"
                ).style("min-width: 52px;"):
                    ui.label(ev["date"].strftime("%d %b")).classes("text-gray-800 font-bold text-xs")
                ui.label(ev["label"]).classes("text-sm text-gray-700 flex-1")
                with ui.element("span").classes(f"text-[10px] font-bold px-2 py-0.5 rounded-full {chip_cls}"):
                    ui.label(chip_label)
