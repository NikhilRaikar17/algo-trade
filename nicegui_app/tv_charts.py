"""
TradingView Lightweight Charts renderers.

Each function renders a chart (or chart pair) directly into the current
NiceGUI element context by injecting a <div> placeholder and scheduling
the chart initialisation JavaScript for after the next DOM sync.
"""

import json
import math
import uuid

from nicegui import ui

from config import SMA_FAST, SMA_SLOW, RSI_OVERBOUGHT, RSI_OVERSOLD


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_IST_OFFSET = 5 * 3600 + 30 * 60  # UTC+5:30 in seconds


def _to_unix(ts) -> int:
    """Convert a pandas Timestamp to a UTC-shifted unix value for IST display.

    Lightweight Charts v4 has no timezone config — it always renders timestamps
    as UTC wall-clock time.  Adding the IST offset (19800 s) makes the chart
    show the correct IST time regardless of the browser's locale.
    """
    if hasattr(ts, "timestamp"):
        return int(ts.timestamp()) + _IST_OFFSET
    return int(ts) + _IST_OFFSET


def _candles_to_tv(candles) -> list:
    """Convert a candles DataFrame to TradingView OHLCV dicts."""
    data = []
    for _, row in candles.iterrows():
        data.append({
            "time": _to_unix(row["timestamp"]),
            "open":  float(row["open"]),
            "high":  float(row["high"]),
            "low":   float(row["low"]),
            "close": float(row["close"]),
        })
    return data


def _safe_float(v) -> float | None:
    """Return float or None when NaN."""
    try:
        f = float(v)
        return None if math.isnan(f) else f
    except (TypeError, ValueError):
        return None


def _dedup_markers(markers: list[dict]) -> list[dict]:
    """
    TradingView silently drops all but the last marker when multiple markers
    share the same unix timestamp.  Merge colliding markers by concatenating
    their text labels separated by '/'.
    """
    seen: dict[int, dict] = {}
    for m in markers:
        t = m["time"]
        if t in seen:
            existing = seen[t]
            # Merge text; keep the higher-priority marker's style (larger size wins)
            merged_text = "/".join(
                p for p in [existing["text"], m["text"]] if p
            )
            if m["size"] >= existing["size"]:
                seen[t] = {**m, "text": merged_text}
            else:
                seen[t] = {**existing, "text": merged_text}
        else:
            seen[t] = m
    return sorted(seen.values(), key=lambda m: m["time"])


_BASE_OPTS = {
    "layout": {
        "background": {"type": "solid", "color": "#ffffff"},
        "textColor": "#374151",
    },
    "grid": {
        "vertLines": {"color": "#f3f4f6"},
        "horzLines": {"color": "#f3f4f6"},
    },
    "crosshair": {"mode": 1},          # CrosshairMode.Normal
    "rightPriceScale": {"borderVisible": False},
    "timeScale": {
        "borderVisible": False,
        "timeVisible": True,
        "secondsVisible": False,
    },
    "handleScroll": True,
    "handleScale": True,
}

_CANDLE_OPTS = {
    "upColor":        "#26a69a",
    "downColor":      "#ef5350",
    "borderUpColor":  "#26a69a",
    "borderDownColor": "#ef5350",
    "wickUpColor":    "#26a69a",
    "wickDownColor":  "#ef5350",
}

# Numeric LineStyle values used in JS
_LS_SOLID       = 0
_LS_DOTTED      = 1
_LS_DASHED      = 2
_LS_LARGE_DASH  = 3


_CHART_HELPER_JS = """
if (!window._tvElWidth) {
    window._tvElWidth = function(el) {
        if (el.clientWidth > 0) return el.clientWidth;
        var p = el.parentElement;
        while (p) { if (p.clientWidth > 0) return p.clientWidth; p = p.parentElement; }
        return window.innerWidth * 0.85;
    };
}
"""

def _schedule_js(js_code: str) -> None:
    """Schedule a JS snippet after the next NiceGUI DOM sync."""
    async def _run():
        await ui.run_javascript(_CHART_HELPER_JS + js_code)

    ui.timer(0.1, _run, once=True)


async def flush_pending_js() -> None:
    """No-op: kept for call-site compatibility. JS is scheduled via timers."""


def _resize_listener(chart_var: str, el_var: str) -> str:
    """Return JS that re-applies chart width on window resize."""
    return (
        f"window.addEventListener('resize', function(){{"
        f"  {chart_var}.applyOptions({{width: {el_var}.clientWidth}});"
        f"}});"
    )


def _ohlc_tooltip_js(chart_var: str, cs_var: str, el_var: str) -> str:
    """Return JS that creates an OHLC tooltip overlay on crosshair move.

    The tooltip is an absolutely-positioned div inside the chart container.
    It shows O / H / L / C values for the bar under the crosshair and hides
    when the cursor leaves the chart.
    """
    return f"""
    (function() {{
        var _tip = document.createElement('div');
        _tip.style.cssText = [
            'position:absolute', 'top:8px', 'left:8px', 'z-index:10',
            'background:rgba(255,255,255,0.88)', 'border:1px solid #e5e7eb',
            'border-radius:4px', 'padding:4px 8px', 'font-size:11px',
            'font-family:monospace', 'line-height:1.6', 'pointer-events:none',
            'display:none',
        ].join(';');
        {el_var}.style.position = 'relative';
        {el_var}.appendChild(_tip);

        {chart_var}.subscribeCrosshairMove(function(param) {{
            if (!param || !param.time || !param.seriesData) {{
                _tip.style.display = 'none';
                return;
            }}
            var bar = param.seriesData.get({cs_var});
            if (!bar) {{ _tip.style.display = 'none'; return; }}
            var clr = bar.close >= bar.open ? '#26a69a' : '#ef5350';
            _tip.innerHTML =
                '<span style="color:#374151">O</span> <b style="color:' + clr + '">' + bar.open.toFixed(2) + '</b>  ' +
                '<span style="color:#374151">H</span> <b style="color:' + clr + '">' + bar.high.toFixed(2) + '</b>  ' +
                '<span style="color:#374151">L</span> <b style="color:' + clr + '">' + bar.low.toFixed(2) + '</b>  ' +
                '<span style="color:#374151">C</span> <b style="color:' + clr + '">' + bar.close.toFixed(2) + '</b>';
            _tip.style.display = 'block';
        }});
    }})();
    """


# ---------------------------------------------------------------------------
# ABCD pattern chart
# ---------------------------------------------------------------------------

_ABCD_COLORS = ["#ff9800", "#2196f3", "#9c27b0", "#00bcd4", "#e91e63"]


def render_tv_abcd_chart(
    candles, swings, patterns, contract_name=None, current_price=None, height: int = 500
) -> None:
    """Render a TradingView candlestick chart with ABCD harmonic overlays."""
    chart_id = f"tv_{uuid.uuid4().hex[:10]}"

    ohlc = _candles_to_tv(candles)

    # Swing-point markers
    markers: list[dict] = []
    for s in swings:
        is_high = s["type"] == "high"
        markers.append({
            "time":     _to_unix(s["time"]),
            "position": "aboveBar" if is_high else "belowBar",
            "color":    "#ef5350" if is_high else "#26a69a",
            "shape":    "arrowDown" if is_high else "arrowUp",
            "text":     "",
            "size":     0.7,
        })

    # ABCD pattern lines + A/B/C/D point labels + target / SL price lines
    pattern_lines: list[dict] = []
    price_lines:   list[dict] = []

    for idx, p in enumerate(patterns):
        color = _ABCD_COLORS[idx % len(_ABCD_COLORS)]
        pts = []
        for key in ("A", "B", "C", "D"):
            pt = p[key]
            t  = _to_unix(pt["time"])
            pts.append({"time": t, "value": float(pt["price"])})
            # Label marker for each ABCD point.
            # Bullish ABCD: A=low, B=high, C=low, D=low (entry).
            # Bearish ABCD: A=high, B=low, C=high, D=high (entry).
            is_bearish = p.get("type", "").lower() == "bearish"
            is_high_pt = (key in ("A", "C")) if is_bearish else (key in ("B",))
            markers.append({
                "time":     t,
                "position": "aboveBar" if is_high_pt else "belowBar",
                "color":    color,
                "shape":    "circle",
                "text":     key,
                "size":     1,
            })

        pattern_lines.append({"data": pts, "color": color})
        price_lines.append({
            "price":  float(p["target"]),
            "color":  "#26a69a",
            "title":  f"T {float(p['target']):.0f}",
            "style":  _LS_DASHED,
        })
        price_lines.append({
            "price":  float(p["stop_loss"]),
            "color":  "#ef5350",
            "title":  f"SL {float(p['stop_loss']):.0f}",
            "style":  _LS_DASHED,
        })

    # Markers must be sorted by time for TradingView
    markers = _dedup_markers(markers)

    ui.html(f'<div id="{chart_id}" style="width:100%; height:{height}px;"></div>', sanitize=False)

    opts = dict(_BASE_OPTS)
    opts["height"] = height

    js = f"""
    (function initAbcd_{chart_id}() {{
        var el = document.getElementById('{chart_id}');
        if (!el) {{ return; }}
        var opts = {json.dumps(opts)};
        opts.width = _tvElWidth(el);
        var chart = LightweightCharts.createChart(el, opts);

        var cs = chart.addCandlestickSeries({json.dumps(_CANDLE_OPTS)});
        cs.setData({json.dumps(ohlc)});
        cs.setMarkers({json.dumps(markers)});

        {json.dumps(pattern_lines)}.forEach(function(p) {{
            var ls = chart.addLineSeries({{
                color: p.color, lineWidth: 2, lineStyle: {_LS_DOTTED},
                crosshairMarkerVisible: false, lastValueVisible: false, priceLineVisible: false,
            }});
            ls.setData(p.data);
        }});

        {json.dumps(price_lines)}.forEach(function(pl) {{
            cs.createPriceLine({{
                price: pl.price, color: pl.color, lineWidth: 1,
                lineStyle: pl.style, axisLabelVisible: true, title: pl.title,
            }});
        }});

        {_ohlc_tooltip_js("chart", "cs", "el")}
        chart.timeScale().fitContent();
        {_resize_listener("chart", "el")}
    }})();
    """
    _schedule_js(js)


# ---------------------------------------------------------------------------
# RSI + SMA chart (two panels)
# ---------------------------------------------------------------------------

def render_tv_rsi_sma_chart(
    candles, df_ind, signals, height: int = 500, rsi_height: int = 200
) -> None:
    """Render candlestick+SMA chart and an RSI panel for the RSI+SMA strategy."""
    price_id = f"tv_{uuid.uuid4().hex[:10]}"
    rsi_id   = f"tv_{uuid.uuid4().hex[:10]}"

    ohlc = _candles_to_tv(candles)

    # Signal markers for price chart
    price_markers: list[dict] = []
    rsi_markers:   list[dict] = []
    for s in signals:
        ts     = _to_unix(s["time"])
        is_buy = s["type"] == "Bullish"
        price_markers.append({
            "time":     ts,
            "position": "belowBar" if is_buy else "aboveBar",
            "color":    "#26a69a" if is_buy else "#ef5350",
            "shape":    "arrowUp" if is_buy else "arrowDown",
            "text":     "B" if is_buy else "S",
            "size":     1.2,
        })
        rsi_markers.append({
            "time":     ts,
            "position": "belowBar" if is_buy else "aboveBar",
            "color":    "#26a69a" if is_buy else "#ef5350",
            "shape":    "arrowUp" if is_buy else "arrowDown",
            "text":     "",
            "size":     0.8,
        })
    price_markers = _dedup_markers(price_markers)
    rsi_markers = _dedup_markers(rsi_markers)

    # Indicator series data
    sma_fast: list[dict] = []
    sma_slow: list[dict] = []
    rsi_data: list[dict] = []

    if df_ind is not None and not df_ind.empty:
        for _, row in df_ind.iterrows():
            ts = _to_unix(row["timestamp"])
            v  = _safe_float(row.get("sma_fast"))
            if v is not None:
                sma_fast.append({"time": ts, "value": v})
            v = _safe_float(row.get("sma_slow"))
            if v is not None:
                sma_slow.append({"time": ts, "value": v})
            v = _safe_float(row.get("rsi"))
            if v is not None:
                rsi_data.append({"time": ts, "value": v})

    ui.html(f'<div id="{price_id}" style="width:100%; height:{height}px;"></div>', sanitize=False)
    ui.html(f'<div id="{rsi_id}" style="width:100%; height:{rsi_height}px; margin-top:4px;"></div>', sanitize=False)

    price_opts = dict(_BASE_OPTS)
    price_opts["height"] = height
    rsi_opts = dict(_BASE_OPTS)
    rsi_opts["height"] = rsi_height

    js = f"""
    (function initRsiSma_{price_id}() {{
        var el  = document.getElementById('{price_id}');
        var el2 = document.getElementById('{rsi_id}');
        if (!el) {{ return; }}

        // ---- Price chart ----
        var opts = {json.dumps(price_opts)};
        opts.width = _tvElWidth(el);
        var chart = LightweightCharts.createChart(el, opts);

        var cs = chart.addCandlestickSeries({json.dumps(_CANDLE_OPTS)});
        cs.setData({json.dumps(ohlc)});
        cs.setMarkers({json.dumps(price_markers)});

        var smaFast = {json.dumps(sma_fast)};
        if (smaFast.length) {{
            chart.addLineSeries({{
                color: '#2196f3', lineWidth: 1.5,
                crosshairMarkerVisible: false, lastValueVisible: true,
                priceLineVisible: false, title: 'SMA {SMA_FAST}',
            }}).setData(smaFast);
        }}
        var smaSlow = {json.dumps(sma_slow)};
        if (smaSlow.length) {{
            chart.addLineSeries({{
                color: '#ff9800', lineWidth: 1.5,
                crosshairMarkerVisible: false, lastValueVisible: true,
                priceLineVisible: false, title: 'SMA {SMA_SLOW}',
            }}).setData(smaSlow);
        }}
        {_ohlc_tooltip_js("chart", "cs", "el")}
        chart.timeScale().fitContent();

        // ---- RSI chart ----
        if (el2) {{
            var opts2 = {json.dumps(rsi_opts)};
            opts2.width = _tvElWidth(el2);
            var rsiChart = LightweightCharts.createChart(el2, opts2);
            var rsiLine = rsiChart.addLineSeries({{
                color: '#9c27b0', lineWidth: 1.5,
                lastValueVisible: true, priceLineVisible: false, title: 'RSI',
            }});
            rsiLine.setData({json.dumps(rsi_data)});
            rsiLine.setMarkers({json.dumps(rsi_markers)});
            rsiLine.createPriceLine({{price: {RSI_OVERBOUGHT}, color: '#ef5350', lineWidth: 1, lineStyle: {_LS_DASHED}, axisLabelVisible: true, title: 'OB'}});
            rsiLine.createPriceLine({{price: {RSI_OVERSOLD},   color: '#26a69a', lineWidth: 1, lineStyle: {_LS_DASHED}, axisLabelVisible: true, title: 'OS'}});
            rsiChart.timeScale().fitContent();

            window.addEventListener('resize', function() {{
                chart.applyOptions({{width: _tvElWidth(el)}});
                rsiChart.applyOptions({{width: _tvElWidth(el2)}});
            }});
        }} else {{
            {_resize_listener("chart", "el")}
        }}
    }})();
    """
    _schedule_js(js)


# ---------------------------------------------------------------------------
# RSI-only chart (two panels)
# ---------------------------------------------------------------------------

def render_tv_rsi_only_chart(
    candles, df_ind, signals, height: int = 500, rsi_height: int = 250
) -> None:
    """Render candlestick chart and RSI panel for the RSI-only strategy."""
    price_id = f"tv_{uuid.uuid4().hex[:10]}"
    rsi_id   = f"tv_{uuid.uuid4().hex[:10]}"

    ohlc = _candles_to_tv(candles)

    # Buy/sell markers + target/SL price lines on price chart
    price_markers: list[dict] = []
    rsi_markers:   list[dict] = []
    price_lines:   list[dict] = []

    for s in signals:
        ts     = _to_unix(s["time"])
        is_buy = s["type"] == "Bullish"
        price_markers.append({
            "time":     ts,
            "position": "belowBar" if is_buy else "aboveBar",
            "color":    "#26a69a" if is_buy else "#ef5350",
            "shape":    "arrowUp" if is_buy else "arrowDown",
            "text":     "B" if is_buy else "S",
            "size":     1.2,
        })

        rsi_v = _safe_float(s.get("rsi"))
        if rsi_v is not None:
            rsi_markers.append({
                "time":     ts,
                "position": "belowBar" if is_buy else "aboveBar",
                "color":    "#26a69a" if is_buy else "#ef5350",
                "shape":    "arrowUp" if is_buy else "arrowDown",
                "text":     "",
                "size":     0.8,
            })

        tgt = _safe_float(s.get("target"))
        sl  = _safe_float(s.get("stop_loss"))
        if tgt is not None:
            price_lines.append({"price": tgt, "color": "#26a69a", "style": _LS_DASHED, "title": ""})
        if sl is not None:
            price_lines.append({"price": sl,  "color": "#ef5350", "style": _LS_DASHED, "title": ""})

    price_markers = _dedup_markers(price_markers)
    rsi_markers = _dedup_markers(rsi_markers)

    # RSI series data
    rsi_data: list[dict] = []
    if df_ind is not None and not df_ind.empty:
        for _, row in df_ind.iterrows():
            v = _safe_float(row.get("rsi"))
            if v is not None:
                rsi_data.append({"time": _to_unix(row["timestamp"]), "value": v})

    ui.html(f'<div id="{price_id}" style="width:100%; height:{height}px;"></div>', sanitize=False)
    ui.html(f'<div id="{rsi_id}" style="width:100%; height:{rsi_height}px; margin-top:4px;"></div>', sanitize=False)

    price_opts = dict(_BASE_OPTS)
    price_opts["height"] = height
    rsi_opts = dict(_BASE_OPTS)
    rsi_opts["height"] = rsi_height

    js = f"""
    (function initRsiOnly_{price_id}() {{
        var el  = document.getElementById('{price_id}');
        var el2 = document.getElementById('{rsi_id}');
        if (!el) {{ return; }}

        // ---- Price chart ----
        var opts = {json.dumps(price_opts)};
        opts.width = _tvElWidth(el);
        var chart = LightweightCharts.createChart(el, opts);

        var cs = chart.addCandlestickSeries({json.dumps(_CANDLE_OPTS)});
        cs.setData({json.dumps(ohlc)});
        cs.setMarkers({json.dumps(price_markers)});

        {json.dumps(price_lines)}.forEach(function(pl) {{
            cs.createPriceLine({{
                price: pl.price, color: pl.color, lineWidth: 1,
                lineStyle: pl.style, axisLabelVisible: false, title: pl.title,
            }});
        }});

        {_ohlc_tooltip_js("chart", "cs", "el")}
        chart.timeScale().fitContent();

        // ---- RSI chart ----
        if (el2) {{
            var opts2 = {json.dumps(rsi_opts)};
            opts2.width = _tvElWidth(el2);
            var rsiChart = LightweightCharts.createChart(el2, opts2);
            var rsiLine = rsiChart.addLineSeries({{
                color: '#9c27b0', lineWidth: 1.5,
                lastValueVisible: true, priceLineVisible: false, title: 'RSI',
            }});
            rsiLine.setData({json.dumps(rsi_data)});
            rsiLine.setMarkers({json.dumps(rsi_markers)});
            rsiLine.createPriceLine({{price: {RSI_OVERBOUGHT}, color: '#ef5350', lineWidth: 1, lineStyle: {_LS_DASHED}, axisLabelVisible: true, title: 'OB'}});
            rsiLine.createPriceLine({{price: {RSI_OVERSOLD},   color: '#26a69a', lineWidth: 1, lineStyle: {_LS_DASHED}, axisLabelVisible: true, title: 'OS'}});
            rsiLine.createPriceLine({{price: 50, color: '#9ca3af', lineWidth: 1, lineStyle: {_LS_DOTTED}, axisLabelVisible: false}});
            rsiChart.timeScale().fitContent();

            window.addEventListener('resize', function() {{
                chart.applyOptions({{width: _tvElWidth(el)}});
                rsiChart.applyOptions({{width: _tvElWidth(el2)}});
            }});
        }} else {{
            {_resize_listener("chart", "el")}
        }}
    }})();
    """
    _schedule_js(js)


# ---------------------------------------------------------------------------
# Double Top chart
# ---------------------------------------------------------------------------

def render_tv_double_top_chart(candles, signals, height: int = 500) -> None:
    """Render a candlestick chart with double top pattern overlays."""
    chart_id = f"tv_{uuid.uuid4().hex[:10]}"

    ohlc = _candles_to_tv(candles)

    markers: list[dict] = []
    price_lines: list[dict] = []

    for s in signals:
        markers.append({
            "time":     _to_unix(s["peak1_time"]),
            "position": "aboveBar",
            "color":    "#ef5350",
            "shape":    "arrowDown",
            "text":     "P1",
            "size":     1.0,
        })
        markers.append({
            "time":     _to_unix(s["peak2_time"]),
            "position": "aboveBar",
            "color":    "#ef5350",
            "shape":    "arrowDown",
            "text":     "P2",
            "size":     1.0,
        })
        markers.append({
            "time":     _to_unix(s["time"]),
            "position": "aboveBar",
            "color":    "#b91c1c",
            "shape":    "arrowDown",
            "text":     "S",
            "size":     1.4,
        })
        price_lines.append({
            "price": s["neckline"],
            "color": "#f59e0b",
            "style": _LS_DASHED,
            "title": f"Neck {s['neckline']:.0f}",
        })
        price_lines.append({
            "price": s["target"],
            "color": "#26a69a",
            "style": _LS_DASHED,
            "title": f"T {s['target']:.0f}",
        })
        price_lines.append({
            "price": s["stop_loss"],
            "color": "#ef5350",
            "style": _LS_DASHED,
            "title": f"SL {s['stop_loss']:.0f}",
        })

    markers = _dedup_markers(markers)

    ui.html(f'<div id="{chart_id}" style="width:100%; height:{height}px;"></div>', sanitize=False)

    opts = dict(_BASE_OPTS)
    opts["height"] = height

    js = f"""
    (function initDT_{chart_id}() {{
        var el = document.getElementById('{chart_id}');
        if (!el) {{ return; }}
        var opts = {json.dumps(opts)};
        opts.width = _tvElWidth(el);
        var chart = LightweightCharts.createChart(el, opts);

        var cs = chart.addCandlestickSeries({json.dumps(_CANDLE_OPTS)});
        cs.setData({json.dumps(ohlc)});
        cs.setMarkers({json.dumps(markers)});

        {json.dumps(price_lines)}.forEach(function(pl) {{
            cs.createPriceLine({{
                price: pl.price, color: pl.color, lineWidth: 1,
                lineStyle: pl.style, axisLabelVisible: true, title: pl.title,
            }});
        }});

        {_ohlc_tooltip_js("chart", "cs", "el")}
        chart.timeScale().fitContent();
        {_resize_listener("chart", "el")}
    }})();
    """
    _schedule_js(js)


# ---------------------------------------------------------------------------
# Double Bottom chart
# ---------------------------------------------------------------------------

def render_tv_double_bottom_chart(candles, signals, height: int = 500) -> None:
    """Render a candlestick chart with double bottom pattern overlays."""
    chart_id = f"tv_{uuid.uuid4().hex[:10]}"

    ohlc = _candles_to_tv(candles)

    markers: list[dict] = []
    price_lines: list[dict] = []

    for s in signals:
        markers.append({
            "time":     _to_unix(s["trough1_time"]),
            "position": "belowBar",
            "color":    "#26a69a",
            "shape":    "arrowUp",
            "text":     "T1",
            "size":     1.0,
        })
        markers.append({
            "time":     _to_unix(s["trough2_time"]),
            "position": "belowBar",
            "color":    "#26a69a",
            "shape":    "arrowUp",
            "text":     "T2",
            "size":     1.0,
        })
        markers.append({
            "time":     _to_unix(s["time"]),
            "position": "belowBar",
            "color":    "#15803d",
            "shape":    "arrowUp",
            "text":     "B",
            "size":     1.4,
        })
        price_lines.append({
            "price": s["neckline"],
            "color": "#f59e0b",
            "style": _LS_DASHED,
            "title": f"Neck {s['neckline']:.0f}",
        })
        price_lines.append({
            "price": s["target"],
            "color": "#26a69a",
            "style": _LS_DASHED,
            "title": f"T {s['target']:.0f}",
        })
        price_lines.append({
            "price": s["stop_loss"],
            "color": "#ef5350",
            "style": _LS_DASHED,
            "title": f"SL {s['stop_loss']:.0f}",
        })

    markers = _dedup_markers(markers)

    ui.html(f'<div id="{chart_id}" style="width:100%; height:{height}px;"></div>', sanitize=False)

    opts = dict(_BASE_OPTS)
    opts["height"] = height

    js = f"""
    (function initDB_{chart_id}() {{
        var el = document.getElementById('{chart_id}');
        if (!el) {{ return; }}
        var opts = {json.dumps(opts)};
        opts.width = _tvElWidth(el);
        var chart = LightweightCharts.createChart(el, opts);

        var cs = chart.addCandlestickSeries({json.dumps(_CANDLE_OPTS)});
        cs.setData({json.dumps(ohlc)});
        cs.setMarkers({json.dumps(markers)});

        {json.dumps(price_lines)}.forEach(function(pl) {{
            cs.createPriceLine({{
                price: pl.price, color: pl.color, lineWidth: 1,
                lineStyle: pl.style, axisLabelVisible: true, title: pl.title,
            }});
        }});

        {_ohlc_tooltip_js("chart", "cs", "el")}
        chart.timeScale().fitContent();
        {_resize_listener("chart", "el")}
    }})();
    """
    _schedule_js(js)


# ---------------------------------------------------------------------------
# Channel Down chart
# ---------------------------------------------------------------------------

def render_tv_channel_down_chart(candles, signals, height: int = 500) -> None:
    """Render candlestick chart with descending channel trendlines and SELL signals."""
    chart_id = f"tv_{uuid.uuid4().hex[:10]}"

    ohlc = _candles_to_tv(candles)
    candle_list = list(candles.iterrows())

    # Build per-signal trendline point lists spanning from H1 to end of candles
    trendlines: list[dict] = []
    for s in signals:
        H1_idx      = s.get("H1_idx", 0)
        H2_idx      = s.get("H2_idx", H1_idx + 1)
        L1_idx      = s.get("L1_idx", H1_idx)
        L2_idx      = s.get("L2_idx", L1_idx)
        H1_price    = float(s["H1"])
        H2_price    = float(s["H2"])
        L1_price    = float(s["L1"])
        L2_price    = float(s["L2"])

        h_bars      = max(H2_idx - H1_idx, 1)
        upper_slope = (H2_price - H1_price) / h_bars
        if L2_idx != L1_idx:
            l_bars      = max(L2_idx - L1_idx, 1)
            lower_slope = (L2_price - L1_price) / l_bars
        else:
            lower_slope = upper_slope

        upper_pts: list[dict] = []
        lower_pts: list[dict] = []
        for pos, (_, row) in enumerate(candle_list):
            if pos < H1_idx:
                continue
            ts = _to_unix(row["timestamp"])
            u = H1_price + upper_slope * (pos - H1_idx)
            l = L1_price + lower_slope * (pos - L1_idx)
            upper_pts.append({"time": ts, "value": round(float(u), 2)})
            lower_pts.append({"time": ts, "value": round(float(l), 2)})

        trendlines.append({"upper": upper_pts, "lower": lower_pts})

    markers: list[dict] = []
    price_lines: list[dict] = []
    for s in signals:
        # Mark the two upper-channel highs (H1, H2) and lower-channel lows (L1, L2)
        markers.append({
            "time":     _to_unix(s["H1_time"]),
            "position": "aboveBar",
            "color":    "#ef5350",
            "shape":    "circle",
            "text":     "H1",
            "size":     0.8,
        })
        markers.append({
            "time":     _to_unix(s["H2_time"]),
            "position": "aboveBar",
            "color":    "#ef5350",
            "shape":    "circle",
            "text":     "H2",
            "size":     0.8,
        })
        markers.append({
            "time":     _to_unix(s["L1_time"]),
            "position": "belowBar",
            "color":    "#3b82f6",
            "shape":    "circle",
            "text":     "L1",
            "size":     0.8,
        })
        markers.append({
            "time":     _to_unix(s["L2_time"]),
            "position": "belowBar",
            "color":    "#3b82f6",
            "shape":    "circle",
            "text":     "L2",
            "size":     0.8,
        })
        markers.append({
            "time":     _to_unix(s["time"]),
            "position": "aboveBar",
            "color":    "#ef5350",
            "shape":    "arrowDown",
            "text":     "S",
            "size":     1.2,
        })
        tgt = _safe_float(s.get("target"))
        sl  = _safe_float(s.get("stop_loss"))
        if tgt is not None:
            price_lines.append({"price": tgt, "color": "#26a69a", "style": _LS_DASHED, "title": f"T {tgt:.0f}"})
        if sl is not None:
            price_lines.append({"price": sl,  "color": "#ef5350", "style": _LS_DASHED, "title": f"SL {sl:.0f}"})

    markers = _dedup_markers(markers)

    ui.html(f'<div id="{chart_id}" style="width:100%; height:{height}px;"></div>', sanitize=False)

    opts = dict(_BASE_OPTS)
    opts["height"] = height

    js = f"""
    (function initCDown_{chart_id}() {{
        var el = document.getElementById('{chart_id}');
        if (!el) {{ return; }}
        var opts = {json.dumps(opts)};
        opts.width = _tvElWidth(el);
        var chart = LightweightCharts.createChart(el, opts);

        var cs = chart.addCandlestickSeries({json.dumps(_CANDLE_OPTS)});
        cs.setData({json.dumps(ohlc)});
        cs.setMarkers({json.dumps(markers)});

        {json.dumps(price_lines)}.forEach(function(pl) {{
            cs.createPriceLine({{
                price: pl.price, color: pl.color, lineWidth: 1,
                lineStyle: pl.style, axisLabelVisible: true, title: pl.title,
            }});
        }});

        var trendlines = {json.dumps(trendlines)};
        trendlines.forEach(function(tl, idx) {{
            if (tl.upper.length) {{
                chart.addLineSeries({{
                    color: '#ef5350', lineWidth: 1.5, lineStyle: {_LS_DASHED},
                    crosshairMarkerVisible: false, lastValueVisible: false,
                    priceLineVisible: false, title: idx === 0 ? 'Upper' : '',
                }}).setData(tl.upper);
            }}
            if (tl.lower.length) {{
                chart.addLineSeries({{
                    color: '#3b82f6', lineWidth: 1.5, lineStyle: {_LS_DASHED},
                    crosshairMarkerVisible: false, lastValueVisible: false,
                    priceLineVisible: false, title: idx === 0 ? 'Lower' : '',
                }}).setData(tl.lower);
            }}
        }});

        {_ohlc_tooltip_js("chart", "cs", "el")}
        chart.timeScale().fitContent();
        {_resize_listener("chart", "el")}
    }})();
    """
    _schedule_js(js)


# ---------------------------------------------------------------------------
# Channel Breakout (Donchian) chart
# ---------------------------------------------------------------------------

def render_tv_channel_breakout_chart(candles, df_ind, signals, height: int = 500) -> None:
    """Render candlestick chart with Donchian channel bands and breakout signals."""
    chart_id = f"tv_{uuid.uuid4().hex[:10]}"

    ohlc = _candles_to_tv(candles)

    upper_data: list[dict] = []
    lower_data: list[dict] = []
    if df_ind is not None and not df_ind.empty:
        for _, row in df_ind.iterrows():
            ts = _to_unix(row["timestamp"])
            v = _safe_float(row.get("upper"))
            if v is not None:
                upper_data.append({"time": ts, "value": v})
            v = _safe_float(row.get("lower"))
            if v is not None:
                lower_data.append({"time": ts, "value": v})

    markers: list[dict] = []
    price_lines: list[dict] = []
    for s in signals:
        ts = _to_unix(s["time"])
        is_buy = s["type"] == "Bullish"
        markers.append({
            "time":     ts,
            "position": "belowBar" if is_buy else "aboveBar",
            "color":    "#26a69a" if is_buy else "#ef5350",
            "shape":    "arrowUp" if is_buy else "arrowDown",
            "text":     "B" if is_buy else "S",
            "size":     1.2,
        })
        tgt = _safe_float(s.get("target"))
        sl  = _safe_float(s.get("stop_loss"))
        if tgt is not None:
            price_lines.append({"price": tgt, "color": "#26a69a", "style": _LS_DASHED, "title": ""})
        if sl is not None:
            price_lines.append({"price": sl,  "color": "#ef5350", "style": _LS_DASHED, "title": ""})

    markers = _dedup_markers(markers)

    ui.html(f'<div id="{chart_id}" style="width:100%; height:{height}px;"></div>', sanitize=False)

    opts = dict(_BASE_OPTS)
    opts["height"] = height

    js = f"""
    (function initCB_{chart_id}() {{
        var el = document.getElementById('{chart_id}');
        if (!el) {{ return; }}
        var opts = {json.dumps(opts)};
        opts.width = _tvElWidth(el);
        var chart = LightweightCharts.createChart(el, opts);

        var cs = chart.addCandlestickSeries({json.dumps(_CANDLE_OPTS)});
        cs.setData({json.dumps(ohlc)});
        cs.setMarkers({json.dumps(markers)});

        {json.dumps(price_lines)}.forEach(function(pl) {{
            cs.createPriceLine({{
                price: pl.price, color: pl.color, lineWidth: 1,
                lineStyle: pl.style, axisLabelVisible: false, title: pl.title,
            }});
        }});

        var upperData = {json.dumps(upper_data)};
        if (upperData.length) {{
            chart.addLineSeries({{
                color: '#3b82f6', lineWidth: 1.5, lineStyle: {_LS_DASHED},
                crosshairMarkerVisible: false, lastValueVisible: true,
                priceLineVisible: false, title: 'Upper',
            }}).setData(upperData);
        }}
        var lowerData = {json.dumps(lower_data)};
        if (lowerData.length) {{
            chart.addLineSeries({{
                color: '#f59e0b', lineWidth: 1.5, lineStyle: {_LS_DASHED},
                crosshairMarkerVisible: false, lastValueVisible: true,
                priceLineVisible: false, title: 'Lower',
            }}).setData(lowerData);
        }}

        {_ohlc_tooltip_js("chart", "cs", "el")}
        chart.timeScale().fitContent();
        {_resize_listener("chart", "el")}
    }})();
    """
    _schedule_js(js)


# ---------------------------------------------------------------------------
# SMA 50 Crossover chart (single panel: candles + SMA 50 line)
# ---------------------------------------------------------------------------

def render_tv_ema10_chart(candles, df_ind, signals, height: int = 500) -> None:
    """Render candlestick chart with EMA 10 overlay and BUY/SELL signal markers."""
    chart_id = f"tv_{uuid.uuid4().hex[:10]}"

    ohlc = _candles_to_tv(candles)

    ema10_data = []
    for _, row in df_ind.iterrows():
        v = _safe_float(row["ema10"])
        if v is not None:
            ema10_data.append({"time": _to_unix(row["timestamp"]), "value": v})

    markers: list[dict] = []
    for s in signals:
        is_buy = s["type"] == "Bullish"
        markers.append({
            "time":     _to_unix(s["time"]),
            "position": "belowBar" if is_buy else "aboveBar",
            "color":    "#26a69a" if is_buy else "#ef5350",
            "shape":    "arrowUp" if is_buy else "arrowDown",
            "text":     "B" if is_buy else "S",
            "size":     1.2,
        })
    markers = _dedup_markers(markers)

    ui.html(f'<div id="{chart_id}" style="width:100%; height:{height}px;"></div>', sanitize=False)

    opts = dict(_BASE_OPTS)
    opts["height"] = height

    js = f"""
    (function initEma10_{chart_id}() {{
        var el = document.getElementById('{chart_id}');
        if (!el) {{ return; }}
        var opts = {json.dumps(opts)};
        opts.width = _tvElWidth(el);
        var chart = LightweightCharts.createChart(el, opts);

        var cs = chart.addCandlestickSeries({json.dumps(_CANDLE_OPTS)});
        cs.setData({json.dumps(ohlc)});
        cs.setMarkers({json.dumps(markers)});

        var ema10Data = {json.dumps(ema10_data)};
        if (ema10Data.length) {{
            chart.addLineSeries({{
                color: '#8b5cf6', lineWidth: 2, lineStyle: {_LS_SOLID},
                crosshairMarkerVisible: false, lastValueVisible: true,
                priceLineVisible: false, title: 'EMA 10',
            }}).setData(ema10Data);
        }}

        {_ohlc_tooltip_js("chart", "cs", "el")}
        chart.timeScale().fitContent();
        {_resize_listener("chart", "el")}
    }})();
    """
    _schedule_js(js)


def render_tv_sma50_chart(candles, df_ind, signals, height: int = 500) -> None:
    """Render candlestick chart with SMA 50 overlay and BUY/SELL signal markers."""
    chart_id = f"tv_{uuid.uuid4().hex[:10]}"

    ohlc = _candles_to_tv(candles)

    # SMA 50 line data
    sma50_data = []
    for _, row in df_ind.iterrows():
        v = _safe_float(row["sma50"])
        if v is not None:
            sma50_data.append({"time": _to_unix(row["timestamp"]), "value": v})

    # BUY / SELL markers
    markers: list[dict] = []
    for s in signals:
        is_buy = s["type"] == "Bullish"
        markers.append({
            "time":     _to_unix(s["time"]),
            "position": "belowBar" if is_buy else "aboveBar",
            "color":    "#26a69a" if is_buy else "#ef5350",
            "shape":    "arrowUp" if is_buy else "arrowDown",
            "text":     "B" if is_buy else "S",
            "size":     1.2,
        })
    markers = _dedup_markers(markers)

    ui.html(f'<div id="{chart_id}" style="width:100%; height:{height}px;"></div>', sanitize=False)

    opts = dict(_BASE_OPTS)
    opts["height"] = height

    js = f"""
    (function initSma50_{chart_id}() {{
        var el = document.getElementById('{chart_id}');
        if (!el) {{ return; }}
        var opts = {json.dumps(opts)};
        opts.width = _tvElWidth(el);
        var chart = LightweightCharts.createChart(el, opts);

        var cs = chart.addCandlestickSeries({json.dumps(_CANDLE_OPTS)});
        cs.setData({json.dumps(ohlc)});
        cs.setMarkers({json.dumps(markers)});

        var sma50Data = {json.dumps(sma50_data)};
        if (sma50Data.length) {{
            chart.addLineSeries({{
                color: '#f59e0b', lineWidth: 2, lineStyle: {_LS_SOLID},
                crosshairMarkerVisible: false, lastValueVisible: true,
                priceLineVisible: false, title: 'SMA 50',
            }}).setData(sma50Data);
        }}

        {_ohlc_tooltip_js("chart", "cs", "el")}
        chart.timeScale().fitContent();
        {_resize_listener("chart", "el")}
    }})();
    """
    _schedule_js(js)


def render_tv_simple_candle_chart(candles, height: int = 300) -> None:
    """Render a plain candlestick chart — used for ATM CE/PE option charts on the dashboard."""
    chart_id = f"tv_{uuid.uuid4().hex[:10]}"
    ohlc = _candles_to_tv(candles)

    ui.html(f'<div id="{chart_id}" style="width:100%; height:{height}px;"></div>', sanitize=False)

    opts = dict(_BASE_OPTS)
    opts["height"] = height

    js = f"""
    (function initSimple_{chart_id}() {{
        var el = document.getElementById('{chart_id}');
        if (!el) {{ return; }}
        var opts = {json.dumps(opts)};
        opts.width = _tvElWidth(el);
        var chart = LightweightCharts.createChart(el, opts);

        var cs = chart.addCandlestickSeries({json.dumps(_CANDLE_OPTS)});
        cs.setData({json.dumps(ohlc)});

        {_ohlc_tooltip_js("chart", "cs", "el")}
        chart.timeScale().fitContent();
        {_resize_listener("chart", "el")}
    }})();
    """
    _schedule_js(js)
