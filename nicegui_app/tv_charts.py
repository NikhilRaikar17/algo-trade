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

def _to_unix(ts) -> int:
    """Convert a pandas Timestamp (or anything with .timestamp()) to Unix seconds."""
    if hasattr(ts, "timestamp"):
        return int(ts.timestamp())
    return int(ts)


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


def _schedule_js(js_code: str) -> None:
    """Schedule a JS snippet after the next NiceGUI DOM sync (100 ms timer)."""
    async def _run():
        await ui.run_javascript(js_code)
    ui.timer(0.1, _run, once=True)


def _resize_listener(chart_var: str, el_var: str) -> str:
    """Return JS that re-applies chart width on window resize."""
    return (
        f"window.addEventListener('resize', function(){{"
        f"  {chart_var}.applyOptions({{width: {el_var}.clientWidth}});"
        f"}});"
    )


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
            # Label marker for each ABCD point
            is_high_pt = key in ("A", "C")
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
    markers.sort(key=lambda m: m["time"])

    ui.html(f'<div id="{chart_id}" style="width:100%; height:{height}px;"></div>')

    opts = dict(_BASE_OPTS)
    opts["height"] = height

    js = f"""
    (function initAbcd_{chart_id}() {{
        var el = document.getElementById('{chart_id}');
        if (!el || !el.clientWidth) {{
            setTimeout(initAbcd_{chart_id}, 50);
            return;
        }}
        var opts = {json.dumps(opts)};
        opts.width = el.clientWidth;
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
    price_markers.sort(key=lambda m: m["time"])
    rsi_markers.sort(key=lambda m: m["time"])

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

    ui.html(f'<div id="{price_id}" style="width:100%; height:{height}px;"></div>')
    ui.html(f'<div id="{rsi_id}" style="width:100%; height:{rsi_height}px; margin-top:4px;"></div>')

    price_opts = dict(_BASE_OPTS)
    price_opts["height"] = height
    rsi_opts = dict(_BASE_OPTS)
    rsi_opts["height"] = rsi_height

    js = f"""
    (function initRsiSma_{price_id}() {{
        var el  = document.getElementById('{price_id}');
        var el2 = document.getElementById('{rsi_id}');
        if (!el || !el.clientWidth) {{
            setTimeout(initRsiSma_{price_id}, 50);
            return;
        }}

        // ---- Price chart ----
        var opts = {json.dumps(price_opts)};
        opts.width = el.clientWidth;
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
        chart.timeScale().fitContent();

        // ---- RSI chart ----
        if (el2) {{
            var opts2 = {json.dumps(rsi_opts)};
            opts2.width = el2.clientWidth || el.clientWidth;
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
                chart.applyOptions({{width: el.clientWidth}});
                rsiChart.applyOptions({{width: el2.clientWidth}});
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

    price_markers.sort(key=lambda m: m["time"])
    rsi_markers.sort(key=lambda m: m["time"])

    # RSI series data
    rsi_data: list[dict] = []
    if df_ind is not None and not df_ind.empty:
        for _, row in df_ind.iterrows():
            v = _safe_float(row.get("rsi"))
            if v is not None:
                rsi_data.append({"time": _to_unix(row["timestamp"]), "value": v})

    ui.html(f'<div id="{price_id}" style="width:100%; height:{height}px;"></div>')
    ui.html(f'<div id="{rsi_id}" style="width:100%; height:{rsi_height}px; margin-top:4px;"></div>')

    price_opts = dict(_BASE_OPTS)
    price_opts["height"] = height
    rsi_opts = dict(_BASE_OPTS)
    rsi_opts["height"] = rsi_height

    js = f"""
    (function initRsiOnly_{price_id}() {{
        var el  = document.getElementById('{price_id}');
        var el2 = document.getElementById('{rsi_id}');
        if (!el || !el.clientWidth) {{
            setTimeout(initRsiOnly_{price_id}, 50);
            return;
        }}

        // ---- Price chart ----
        var opts = {json.dumps(price_opts)};
        opts.width = el.clientWidth;
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

        chart.timeScale().fitContent();

        // ---- RSI chart ----
        if (el2) {{
            var opts2 = {json.dumps(rsi_opts)};
            opts2.width = el2.clientWidth || el.clientWidth;
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
                chart.applyOptions({{width: el.clientWidth}});
                rsiChart.applyOptions({{width: el2.clientWidth}});
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

    markers.sort(key=lambda m: m["time"])

    ui.html(f'<div id="{chart_id}" style="width:100%; height:{height}px;"></div>')

    opts = dict(_BASE_OPTS)
    opts["height"] = height

    js = f"""
    (function initDT_{chart_id}() {{
        var el = document.getElementById('{chart_id}');
        if (!el || !el.clientWidth) {{
            setTimeout(initDT_{chart_id}, 50);
            return;
        }}
        var opts = {json.dumps(opts)};
        opts.width = el.clientWidth;
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

    markers.sort(key=lambda m: m["time"])

    ui.html(f'<div id="{chart_id}" style="width:100%; height:{height}px;"></div>')

    opts = dict(_BASE_OPTS)
    opts["height"] = height

    js = f"""
    (function initDB_{chart_id}() {{
        var el = document.getElementById('{chart_id}');
        if (!el || !el.clientWidth) {{
            setTimeout(initDB_{chart_id}, 50);
            return;
        }}
        var opts = {json.dumps(opts)};
        opts.width = el.clientWidth;
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

    markers.sort(key=lambda m: m["time"])

    ui.html(f'<div id="{chart_id}" style="width:100%; height:{height}px;"></div>')

    opts = dict(_BASE_OPTS)
    opts["height"] = height

    js = f"""
    (function initCB_{chart_id}() {{
        var el = document.getElementById('{chart_id}');
        if (!el || !el.clientWidth) {{
            setTimeout(initCB_{chart_id}, 50);
            return;
        }}
        var opts = {json.dumps(opts)};
        opts.width = el.clientWidth;
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

        chart.timeScale().fitContent();
        {_resize_listener("chart", "el")}
    }})();
    """
    _schedule_js(js)
