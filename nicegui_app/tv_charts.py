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
        "background": {"type": "solid", "color": "#0a0d10"},
        "textColor": "#8a97a3",
    },
    "grid": {
        "vertLines": {"color": "#1a2128"},
        "horzLines": {"color": "#1a2128"},
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
if (!window._tvInitWhenVisible) {
    window._tvInitWhenVisible = function(elId, initFn) {
        var el = document.getElementById(elId);
        if (!el) return;
        if (el.clientWidth > 0) { initFn(el); return; }
        var ro = new ResizeObserver(function(entries) {
            for (var e of entries) {
                if (e.contentRect.width > 0) { ro.disconnect(); initFn(el); return; }
            }
        });
        ro.observe(el);
    };
}
if (!window._tvChartInstances) {
    window._tvChartInstances = [];
    window._tvThemeOpts = function(isLight) {
        return isLight ? {
            layout: { background: { type: 'solid', color: '#f5f7fa' }, textColor: '#3d4a57' },
            grid: { vertLines: { color: '#e0e4ea' }, horzLines: { color: '#e0e4ea' } }
        } : {
            layout: { background: { type: 'solid', color: '#0a0d10' }, textColor: '#8a97a3' },
            grid: { vertLines: { color: '#1a2128' }, horzLines: { color: '#1a2128' } }
        };
    };
    window._tvApplyTheme = function(isLight) {
        var opts = window._tvThemeOpts(isLight);
        window._tvChartInstances.forEach(function(c) { try { c.applyOptions(opts); } catch(e) {} });
    };
    (new MutationObserver(function() {
        window._tvApplyTheme(document.body.classList.contains('at-light-theme'));
    })).observe(document.body, { attributes: true, attributeFilter: ['class'] });
}
"""

def _schedule_js(js_code: str) -> None:
    """Schedule a JS snippet after the next NiceGUI DOM sync."""
    async def _run():
        await ui.run_javascript(_CHART_HELPER_JS + js_code)

    ui.timer(0.8, _run, once=True)


async def flush_pending_js() -> None:
    """No-op: kept for call-site compatibility. JS is scheduled via timers."""


def _resize_listener(chart_var: str, el_var: str) -> str:
    """Return JS that re-applies chart width on window resize and on first visibility (hidden tab fix)."""
    return (
        f"window.addEventListener('resize', function(){{"
        f"  {chart_var}.applyOptions({{width: _tvElWidth({el_var})}});"
        f"}});"
        f"(new ResizeObserver(function(en,ob){{"
        f"  if(en[0].contentRect.width>0){{"
        f"    ob.disconnect();"
        f"    {chart_var}.applyOptions({{width:en[0].contentRect.width}});"
        f"    {chart_var}.timeScale().fitContent();"
        f"  }}"
        f"}})).observe({el_var});"
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
        _tip.className = 'tv-ohlc-tip';
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
                '<span>O</span> <b style="color:' + clr + '">' + bar.open.toFixed(2) + '</b>  ' +
                '<span>H</span> <b style="color:' + clr + '">' + bar.high.toFixed(2) + '</b>  ' +
                '<span>L</span> <b style="color:' + clr + '">' + bar.low.toFixed(2) + '</b>  ' +
                '<span>C</span> <b style="color:' + clr + '">' + bar.close.toFixed(2) + '</b>';
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
) -> str:
    """Render a TradingView candlestick chart with ABCD harmonic overlays.

    Returns chart_id so callers can invoke window._tvShowTrade_<chart_id>(patternIdx)
    to highlight a specific pattern on row click.  The chart starts clean (no markers).
    """
    chart_id = f"tv_{uuid.uuid4().hex[:10]}"

    ohlc = _candles_to_tv(candles)

    # Build per-pattern data: markers + pattern line points + price lines
    per_pattern: list[dict] = []
    for idx, p in enumerate(patterns):
        color = _ABCD_COLORS[idx % len(_ABCD_COLORS)]
        pts = []
        pt_markers: list[dict] = []
        for key in ("A", "B", "C", "D"):
            pt = p[key]
            t  = _to_unix(pt["time"])
            pts.append({"time": t, "value": float(pt["price"])})
            is_bearish = p.get("type", "").lower() == "bearish"
            is_high_pt = (key in ("A", "C")) if is_bearish else (key in ("B",))
            pt_markers.append({
                "time":     t,
                "position": "aboveBar" if is_high_pt else "belowBar",
                "color":    color,
                "shape":    "circle",
                "text":     key,
                "size":     1,
            })
        per_pattern.append({
            "color":      color,
            "line_pts":   pts,
            "markers":    _dedup_markers(pt_markers),
            "target":     float(p["target"]),
            "stop_loss":  float(p["stop_loss"]),
            "target_lbl": f"T {float(p['target']):.0f}",
            "sl_lbl":     f"SL {float(p['stop_loss']):.0f}",
        })

    ui.html(f'<div class="at-chart-wrap"><div id="{chart_id}" style="width:100%; height:{height}px;"></div></div>', sanitize=False)

    opts = dict(_BASE_OPTS)
    opts["height"] = height

    js = f"""
    (function initAbcd_{chart_id}() {{
        var el = document.getElementById('{chart_id}');
        if (!el) {{ return; }}
        var opts = {json.dumps(opts)};
        opts.width = _tvElWidth(el);
        var chart = LightweightCharts.createChart(el, opts);
        window._tvChartInstances.push(chart);
        chart.applyOptions(window._tvThemeOpts(document.body.classList.contains('at-light-theme')));

        var cs = chart.addCandlestickSeries({json.dumps(_CANDLE_OPTS)});
        cs.setData({json.dumps(ohlc)});
        // Start with no markers
        cs.setMarkers([]);

        var perPattern = {json.dumps(per_pattern)};
        // Track active overlay series so we can remove them on next click
        var _activeLines = [];
        var _activePriceLines = [];

        window._tvShowTrade_{chart_id} = function(idx) {{
            // Remove previous overlays
            _activeLines.forEach(function(ls) {{ try {{ chart.removeSeries(ls); }} catch(e) {{}} }});
            _activeLines = [];
            _activePriceLines.forEach(function(pl) {{ try {{ cs.removePriceLine(pl); }} catch(e) {{}} }});
            _activePriceLines = [];
            cs.setMarkers([]);

            if (idx < 0 || idx >= perPattern.length) return;
            var p = perPattern[idx];

            // Pattern connecting line
            var ls = chart.addLineSeries({{
                color: p.color, lineWidth: 2, lineStyle: {_LS_DOTTED},
                crosshairMarkerVisible: false, lastValueVisible: false, priceLineVisible: false,
            }});
            ls.setData(p.line_pts);
            _activeLines.push(ls);

            // A/B/C/D point markers
            cs.setMarkers(p.markers);

            // Target and SL price lines
            _activePriceLines.push(cs.createPriceLine({{
                price: p.target, color: '#26a69a', lineWidth: 1,
                lineStyle: {_LS_DASHED}, axisLabelVisible: true, title: p.target_lbl,
            }}));
            _activePriceLines.push(cs.createPriceLine({{
                price: p.stop_loss, color: '#ef5350', lineWidth: 1,
                lineStyle: {_LS_DASHED}, axisLabelVisible: true, title: p.sl_lbl,
            }}));

            // Scroll the chart to show the pattern's D point (entry)
            var entryTime = p.line_pts[p.line_pts.length - 1].time;
            chart.timeScale().scrollToPosition(0, false);
            chart.timeScale().setVisibleRange({{
                from: p.line_pts[0].time - 3600,
                to:   entryTime + 7200,
            }});
        }};

        {_ohlc_tooltip_js("chart", "cs", "el")}
        chart.timeScale().fitContent();
        {_resize_listener("chart", "el")}
    }})();
    """
    _schedule_js(js)
    return chart_id


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

    ui.html(f'<div class="at-chart-wrap"><div id="{price_id}" style="width:100%; height:{height}px;"></div></div>', sanitize=False)
    ui.html(f'<div class="at-chart-wrap" style="margin-top:6px;"><div id="{rsi_id}" style="width:100%; height:{rsi_height}px;"></div></div>', sanitize=False)

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
        window._tvChartInstances.push(chart);
        chart.applyOptions(window._tvThemeOpts(document.body.classList.contains('at-light-theme')));

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
            window._tvChartInstances.push(rsiChart);
            rsiChart.applyOptions(window._tvThemeOpts(document.body.classList.contains('at-light-theme')));
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
# Double Top chart
# ---------------------------------------------------------------------------

def render_tv_double_top_custom_chart(candles, signals, height: int = 500) -> str:
    """Render a candlestick chart with double top pattern overlays.

    Returns chart_id. Chart starts clean; call window._tvShowTrade_<chart_id>(idx)
    on row click to highlight a specific signal.
    """
    chart_id = f"tv_{uuid.uuid4().hex[:10]}"

    ohlc = _candles_to_tv(candles)

    per_signal: list[dict] = []
    for s in signals:
        mkrs = _dedup_markers([
            {"time": _to_unix(s["peak1_time"]), "position": "aboveBar", "color": "#ef5350", "shape": "arrowDown", "text": "P1", "size": 1.0},
            {"time": _to_unix(s["peak2_time"]), "position": "aboveBar", "color": "#ef5350", "shape": "arrowDown", "text": "P2", "size": 1.0},
            {"time": _to_unix(s["time"]),       "position": "aboveBar", "color": "#b91c1c", "shape": "arrowDown", "text": "S",  "size": 1.4},
        ])
        per_signal.append({
            "markers":   mkrs,
            "neckline":  float(s["neckline"]),
            "target":    float(s["target"]),
            "stop_loss": float(s["stop_loss"]),
            "from_time": _to_unix(s["peak1_time"]) - 3600,
            "to_time":   _to_unix(s["time"]) + 7200,
        })

    ui.html(f'<div class="at-chart-wrap"><div id="{chart_id}" style="width:100%; height:{height}px;"></div></div>', sanitize=False)

    opts = dict(_BASE_OPTS)
    opts["height"] = height

    js = f"""
    (function initDT_{chart_id}() {{
        var el = document.getElementById('{chart_id}');
        if (!el) {{ return; }}
        var opts = {json.dumps(opts)};
        opts.width = _tvElWidth(el);
        var chart = LightweightCharts.createChart(el, opts);
        window._tvChartInstances.push(chart);
        chart.applyOptions(window._tvThemeOpts(document.body.classList.contains('at-light-theme')));

        var cs = chart.addCandlestickSeries({json.dumps(_CANDLE_OPTS)});
        cs.setData({json.dumps(ohlc)});
        cs.setMarkers([]);

        var perSignal = {json.dumps(per_signal)};
        var _activePriceLines = [];

        window._tvShowTrade_{chart_id} = function(idx) {{
            cs.setMarkers([]);
            _activePriceLines.forEach(function(pl) {{ try {{ cs.removePriceLine(pl); }} catch(e) {{}} }});
            _activePriceLines = [];
            if (idx < 0 || idx >= perSignal.length) return;
            var s = perSignal[idx];
            cs.setMarkers(s.markers);
            _activePriceLines.push(cs.createPriceLine({{ price: s.neckline,  color: '#f59e0b', lineWidth: 1, lineStyle: {_LS_DASHED}, axisLabelVisible: true, title: 'Neck ' + s.neckline.toFixed(0) }}));
            _activePriceLines.push(cs.createPriceLine({{ price: s.target,    color: '#26a69a', lineWidth: 1, lineStyle: {_LS_DASHED}, axisLabelVisible: true, title: 'T ' + s.target.toFixed(0) }}));
            _activePriceLines.push(cs.createPriceLine({{ price: s.stop_loss, color: '#ef5350', lineWidth: 1, lineStyle: {_LS_DASHED}, axisLabelVisible: true, title: 'SL ' + s.stop_loss.toFixed(0) }}));
            chart.timeScale().setVisibleRange({{ from: s.from_time, to: s.to_time }});
        }};

        {_ohlc_tooltip_js("chart", "cs", "el")}
        chart.timeScale().fitContent();
        {_resize_listener("chart", "el")}
    }})();
    """
    _schedule_js(js)
    return chart_id


def render_tv_double_top_standard_chart(candles, signals, height: int = 500) -> str:
    """Render a candlestick chart with double top standard pattern overlays."""
    chart_id = f"tv_{uuid.uuid4().hex[:10]}"

    ohlc = _candles_to_tv(candles)

    per_signal: list[dict] = []
    for s in signals:
        mkrs = _dedup_markers([
            {"time": _to_unix(s["peak1_time"]), "position": "aboveBar", "color": "#ef5350", "shape": "arrowDown", "text": "P1", "size": 1.0},
            {"time": _to_unix(s["peak2_time"]), "position": "aboveBar", "color": "#ef5350", "shape": "arrowDown", "text": "P2", "size": 1.0},
            {"time": _to_unix(s["time"]),       "position": "aboveBar", "color": "#b91c1c", "shape": "arrowDown", "text": "S",  "size": 1.4},
        ])
        per_signal.append({
            "markers":   mkrs,
            "neckline":  float(s["neckline"]),
            "target":    float(s["target"]),
            "stop_loss": float(s["stop_loss"]),
            "from_time": _to_unix(s["peak1_time"]) - 3600,
            "to_time":   _to_unix(s["time"]) + 7200,
        })

    ui.html(f'<div class="at-chart-wrap"><div id="{chart_id}" style="width:100%; height:{height}px;"></div></div>', sanitize=False)

    opts = dict(_BASE_OPTS)
    opts["height"] = height

    js = f"""
    (function initDTS_{chart_id}() {{
        var el = document.getElementById('{chart_id}');
        if (!el) {{ return; }}
        var opts = {json.dumps(opts)};
        opts.width = _tvElWidth(el);
        var chart = LightweightCharts.createChart(el, opts);
        window._tvChartInstances.push(chart);
        chart.applyOptions(window._tvThemeOpts(document.body.classList.contains('at-light-theme')));

        var cs = chart.addCandlestickSeries({json.dumps(_CANDLE_OPTS)});
        cs.setData({json.dumps(ohlc)});
        cs.setMarkers([]);

        var perSignal = {json.dumps(per_signal)};
        var _activePriceLines = [];

        window._tvShowTrade_{chart_id} = function(idx) {{
            cs.setMarkers([]);
            _activePriceLines.forEach(function(pl) {{ try {{ cs.removePriceLine(pl); }} catch(e) {{}} }});
            _activePriceLines = [];
            if (idx < 0 || idx >= perSignal.length) return;
            var s = perSignal[idx];
            cs.setMarkers(s.markers);
            _activePriceLines.push(cs.createPriceLine({{ price: s.neckline,  color: '#f59e0b', lineWidth: 1, lineStyle: {_LS_DASHED}, axisLabelVisible: true, title: 'Neck ' + s.neckline.toFixed(0) }}));
            _activePriceLines.push(cs.createPriceLine({{ price: s.target,    color: '#26a69a', lineWidth: 1, lineStyle: {_LS_DASHED}, axisLabelVisible: true, title: 'T ' + s.target.toFixed(0) }}));
            _activePriceLines.push(cs.createPriceLine({{ price: s.stop_loss, color: '#ef5350', lineWidth: 1, lineStyle: {_LS_DASHED}, axisLabelVisible: true, title: 'SL ' + s.stop_loss.toFixed(0) }}));
            chart.timeScale().setVisibleRange({{ from: s.from_time, to: s.to_time }});
        }};

        {_ohlc_tooltip_js("chart", "cs", "el")}
        chart.timeScale().fitContent();
        {_resize_listener("chart", "el")}
    }})();
    """
    _schedule_js(js)
    return chart_id


# ---------------------------------------------------------------------------
# Double Bottom chart
# ---------------------------------------------------------------------------

def render_tv_double_bottom_chart(candles, signals, height: int = 500) -> None:
    """Render a candlestick chart with double bottom pattern overlays.

    Returns chart_id. Chart starts clean; call window._tvShowTrade_<chart_id>(idx)
    on row click to highlight a specific signal.
    """
    chart_id = f"tv_{uuid.uuid4().hex[:10]}"

    ohlc = _candles_to_tv(candles)

    per_signal: list[dict] = []
    for s in signals:
        mkrs = _dedup_markers([
            {"time": _to_unix(s["trough1_time"]), "position": "belowBar", "color": "#26a69a", "shape": "arrowUp", "text": "T1", "size": 1.0},
            {"time": _to_unix(s["trough2_time"]), "position": "belowBar", "color": "#26a69a", "shape": "arrowUp", "text": "T2", "size": 1.0},
            {"time": _to_unix(s["time"]),         "position": "belowBar", "color": "#15803d", "shape": "arrowUp", "text": "B",  "size": 1.4},
        ])
        per_signal.append({
            "markers":   mkrs,
            "neckline":  float(s["neckline"]),
            "target":    float(s["target"]),
            "stop_loss": float(s["stop_loss"]),
            "from_time": _to_unix(s["trough1_time"]) - 3600,
            "to_time":   _to_unix(s["time"]) + 7200,
        })

    ui.html(f'<div class="at-chart-wrap"><div id="{chart_id}" style="width:100%; height:{height}px;"></div></div>', sanitize=False)

    opts = dict(_BASE_OPTS)
    opts["height"] = height

    js = f"""
    (function initDB_{chart_id}() {{
        var el = document.getElementById('{chart_id}');
        if (!el) {{ return; }}
        var opts = {json.dumps(opts)};
        opts.width = _tvElWidth(el);
        var chart = LightweightCharts.createChart(el, opts);
        window._tvChartInstances.push(chart);
        chart.applyOptions(window._tvThemeOpts(document.body.classList.contains('at-light-theme')));

        var cs = chart.addCandlestickSeries({json.dumps(_CANDLE_OPTS)});
        cs.setData({json.dumps(ohlc)});
        cs.setMarkers([]);

        var perSignal = {json.dumps(per_signal)};
        var _activePriceLines = [];

        window._tvShowTrade_{chart_id} = function(idx) {{
            cs.setMarkers([]);
            _activePriceLines.forEach(function(pl) {{ try {{ cs.removePriceLine(pl); }} catch(e) {{}} }});
            _activePriceLines = [];
            if (idx < 0 || idx >= perSignal.length) return;
            var s = perSignal[idx];
            cs.setMarkers(s.markers);
            _activePriceLines.push(cs.createPriceLine({{ price: s.neckline,  color: '#f59e0b', lineWidth: 1, lineStyle: {_LS_DASHED}, axisLabelVisible: true, title: 'Neck ' + s.neckline.toFixed(0) }}));
            _activePriceLines.push(cs.createPriceLine({{ price: s.target,    color: '#26a69a', lineWidth: 1, lineStyle: {_LS_DASHED}, axisLabelVisible: true, title: 'T ' + s.target.toFixed(0) }}));
            _activePriceLines.push(cs.createPriceLine({{ price: s.stop_loss, color: '#ef5350', lineWidth: 1, lineStyle: {_LS_DASHED}, axisLabelVisible: true, title: 'SL ' + s.stop_loss.toFixed(0) }}));
            chart.timeScale().setVisibleRange({{ from: s.from_time, to: s.to_time }});
        }};

        {_ohlc_tooltip_js("chart", "cs", "el")}
        chart.timeScale().fitContent();
        {_resize_listener("chart", "el")}
    }})();
    """
    _schedule_js(js)
    return chart_id


# ---------------------------------------------------------------------------
# EMA 10 / SMA 50 charts
# ---------------------------------------------------------------------------

def render_tv_ema10_chart(candles, df_ind, signals, height: int = 500) -> str:
    """Render candlestick chart with EMA 10 overlay and BUY/SELL signal markers.

    Returns chart_id. Chart starts with no markers; call window._tvShowTrade_<chart_id>(idx).
    """
    chart_id = f"tv_{uuid.uuid4().hex[:10]}"

    ohlc = _candles_to_tv(candles)

    ema10_data = []
    for _, row in df_ind.iterrows():
        v = _safe_float(row["ema10"])
        if v is not None:
            ema10_data.append({"time": _to_unix(row["timestamp"]), "value": v})

    per_signal: list[dict] = []
    for s in signals:
        is_buy = s["type"] == "Bullish"
        ts = _to_unix(s["time"])
        per_signal.append({
            "marker": {
                "time":     ts,
                "position": "belowBar" if is_buy else "aboveBar",
                "color":    "#26a69a" if is_buy else "#ef5350",
                "shape":    "arrowUp" if is_buy else "arrowDown",
                "text":     "B" if is_buy else "S",
                "size":     1.2,
            },
            "target":    float(s.get("target") or 0),
            "stop_loss": float(s.get("stop_loss") or 0),
            "from_time": ts - 3600,
            "to_time":   ts + 7200,
        })

    ui.html(f'<div class="at-chart-wrap"><div id="{chart_id}" style="width:100%; height:{height}px;"></div></div>', sanitize=False)

    opts = dict(_BASE_OPTS)
    opts["height"] = height

    js = f"""
    (function initEma10_{chart_id}() {{
        var el = document.getElementById('{chart_id}');
        if (!el) {{ return; }}
        var opts = {json.dumps(opts)};
        opts.width = _tvElWidth(el);
        var chart = LightweightCharts.createChart(el, opts);
        window._tvChartInstances.push(chart);
        chart.applyOptions(window._tvThemeOpts(document.body.classList.contains('at-light-theme')));

        var cs = chart.addCandlestickSeries({json.dumps(_CANDLE_OPTS)});
        cs.setData({json.dumps(ohlc)});
        cs.setMarkers([]);

        var ema10Data = {json.dumps(ema10_data)};
        if (ema10Data.length) {{
            chart.addLineSeries({{
                color: '#10b981', lineWidth: 2, lineStyle: {_LS_SOLID},
                crosshairMarkerVisible: false, lastValueVisible: true,
                priceLineVisible: false, title: 'EMA 10',
            }}).setData(ema10Data);
        }}

        var perSignal = {json.dumps(per_signal)};
        var _activePriceLines = [];

        window._tvShowTrade_{chart_id} = function(idx) {{
            cs.setMarkers([]);
            _activePriceLines.forEach(function(pl) {{ try {{ cs.removePriceLine(pl); }} catch(e) {{}} }});
            _activePriceLines = [];
            if (idx < 0 || idx >= perSignal.length) return;
            var s = perSignal[idx];
            cs.setMarkers([s.marker]);
            if (s.target) _activePriceLines.push(cs.createPriceLine({{ price: s.target,    color: '#26a69a', lineWidth: 1, lineStyle: {_LS_DASHED}, axisLabelVisible: true, title: 'T ' + s.target.toFixed(0) }}));
            if (s.stop_loss) _activePriceLines.push(cs.createPriceLine({{ price: s.stop_loss, color: '#ef5350', lineWidth: 1, lineStyle: {_LS_DASHED}, axisLabelVisible: true, title: 'SL ' + s.stop_loss.toFixed(0) }}));
            chart.timeScale().setVisibleRange({{ from: s.from_time, to: s.to_time }});
        }};

        {_ohlc_tooltip_js("chart", "cs", "el")}
        chart.timeScale().fitContent();
        {_resize_listener("chart", "el")}
    }})();
    """
    _schedule_js(js)
    return chart_id


def render_tv_sma50_chart(candles, df_ind, signals, height: int = 500) -> str:
    """Render candlestick chart with SMA 50 overlay and BUY/SELL signal markers.

    Returns chart_id. Chart starts with no markers; call window._tvShowTrade_<chart_id>(idx).
    """
    chart_id = f"tv_{uuid.uuid4().hex[:10]}"

    ohlc = _candles_to_tv(candles)

    sma50_data = []
    for _, row in df_ind.iterrows():
        v = _safe_float(row["sma50"])
        if v is not None:
            sma50_data.append({"time": _to_unix(row["timestamp"]), "value": v})

    per_signal: list[dict] = []
    for s in signals:
        is_buy = s["type"] == "Bullish"
        ts = _to_unix(s["time"])
        per_signal.append({
            "marker": {
                "time":     ts,
                "position": "belowBar" if is_buy else "aboveBar",
                "color":    "#26a69a" if is_buy else "#ef5350",
                "shape":    "arrowUp" if is_buy else "arrowDown",
                "text":     "B" if is_buy else "S",
                "size":     1.2,
            },
            "target":    float(s.get("target") or 0),
            "stop_loss": float(s.get("stop_loss") or 0),
            "from_time": ts - 3600,
            "to_time":   ts + 7200,
        })

    ui.html(f'<div class="at-chart-wrap"><div id="{chart_id}" style="width:100%; height:{height}px;"></div></div>', sanitize=False)

    opts = dict(_BASE_OPTS)
    opts["height"] = height

    js = f"""
    (function initSma50_{chart_id}() {{
        var el = document.getElementById('{chart_id}');
        if (!el) {{ return; }}
        var opts = {json.dumps(opts)};
        opts.width = _tvElWidth(el);
        var chart = LightweightCharts.createChart(el, opts);
        window._tvChartInstances.push(chart);
        chart.applyOptions(window._tvThemeOpts(document.body.classList.contains('at-light-theme')));

        var cs = chart.addCandlestickSeries({json.dumps(_CANDLE_OPTS)});
        cs.setData({json.dumps(ohlc)});
        cs.setMarkers([]);

        var sma50Data = {json.dumps(sma50_data)};
        if (sma50Data.length) {{
            chart.addLineSeries({{
                color: '#f59e0b', lineWidth: 2, lineStyle: {_LS_SOLID},
                crosshairMarkerVisible: false, lastValueVisible: true,
                priceLineVisible: false, title: 'SMA 50',
            }}).setData(sma50Data);
        }}

        var perSignal = {json.dumps(per_signal)};
        var _activePriceLines = [];

        window._tvShowTrade_{chart_id} = function(idx) {{
            cs.setMarkers([]);
            _activePriceLines.forEach(function(pl) {{ try {{ cs.removePriceLine(pl); }} catch(e) {{}} }});
            _activePriceLines = [];
            if (idx < 0 || idx >= perSignal.length) return;
            var s = perSignal[idx];
            cs.setMarkers([s.marker]);
            if (s.target) _activePriceLines.push(cs.createPriceLine({{ price: s.target,    color: '#26a69a', lineWidth: 1, lineStyle: {_LS_DASHED}, axisLabelVisible: true, title: 'T ' + s.target.toFixed(0) }}));
            if (s.stop_loss) _activePriceLines.push(cs.createPriceLine({{ price: s.stop_loss, color: '#ef5350', lineWidth: 1, lineStyle: {_LS_DASHED}, axisLabelVisible: true, title: 'SL ' + s.stop_loss.toFixed(0) }}));
            chart.timeScale().setVisibleRange({{ from: s.from_time, to: s.to_time }});
        }};

        {_ohlc_tooltip_js("chart", "cs", "el")}
        chart.timeScale().fitContent();
        {_resize_listener("chart", "el")}
    }})();
    """
    _schedule_js(js)
    return chart_id


def render_tv_simple_candle_chart(candles, height: int = 300) -> None:
    """Render a plain candlestick chart — used for ATM CE/PE option charts on the dashboard."""
    chart_id = f"tv_{uuid.uuid4().hex[:10]}"
    ohlc = _candles_to_tv(candles)

    ui.html(f'<div class="at-chart-wrap"><div id="{chart_id}" style="width:100%; height:{height}px;"></div></div>', sanitize=False)

    opts = dict(_BASE_OPTS)
    opts["height"] = height

    js = f"""
    (function initSimple_{chart_id}() {{
        var el = document.getElementById('{chart_id}');
        if (!el) {{ return; }}
        var opts = {json.dumps(opts)};
        opts.width = _tvElWidth(el);
        var chart = LightweightCharts.createChart(el, opts);
        window._tvChartInstances.push(chart);
        chart.applyOptions(window._tvThemeOpts(document.body.classList.contains('at-light-theme')));

        var cs = chart.addCandlestickSeries({json.dumps(_CANDLE_OPTS)});
        cs.setData({json.dumps(ohlc)});

        {_ohlc_tooltip_js("chart", "cs", "el")}
        chart.timeScale().fitContent();
        {_resize_listener("chart", "el")}
    }})();
    """
    _schedule_js(js)
