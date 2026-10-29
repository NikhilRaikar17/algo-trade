"""
Top Stocks Scanner: top 5 gainers / 5 losers of the NIFTY 50 today, ranked by % change.
The background loop in main.py is the only writer (every 5 min in market hours); this page
just shows its latest result.
Click a card to open a 25-min chart (5 days) in a modal.
"""

import asyncio
import json
import time
import traceback
import uuid

from nicegui import ui, context

from config import dhan, now_ist
from data import nifty50_stocks, _fetch_any_stock_candles, _candles_to_daily_change
from db import sync_top_stocks
from state import api_call, is_market_open
from tv_charts import _BASE_OPTS, _CANDLE_OPTS, _schedule_js, _candles_to_tv, _resize_listener, _ohlc_tooltip_js


TOP_N = 5            # gainers and losers shown / traded
KEEP_RANK = 8        # a stock already on the list stays while it ranks within this on its side
MIN_COVERAGE = 45    # of 50: below this the ranking is too partial to replace the list
_PAUSE_SECONDS = 0.35  # between per-stock requests; back-to-back calls get rate-limited


def quote_changes(quotes: dict, universe: list[dict]) -> list[dict]:
    """Today's change for each stock from Dhan's quote payload ({security_id: quote}); "close" there is
    the official previous close, as broker apps use. Stocks without a price yet are left out."""
    results = []
    for stock in universe:
        q = quotes.get(str(stock["security_id"])) or {}
        ohlc, ltp = q.get("ohlc") or {}, q.get("last_price")
        prev = ohlc.get("close")
        if not ltp or not prev:
            continue
        ltp, prev = float(ltp), float(prev)
        change = ltp - prev
        results.append({
            "name":        stock["name"],
            "security_id": stock["security_id"],
            "data": {
                "current":    round(ltp, 2),
                "prev_close": round(prev, 2),
                "open":       round(float(ohlc.get("open") or ltp), 2),
                "high":       round(max(float(ohlc.get("high") or ltp), ltp), 2),
                "low":        round(min(float(ohlc.get("low") or ltp), ltp), 2),
                "change":     round(change, 2),
                "change_pct": round(change / prev * 100, 2),
                "is_green":   change >= 0,
            },
        })
    return results


def _quote_results(universe: list[dict]) -> list[dict]:
    """The whole universe from one bulk quote call (Dhan takes up to 1000 instruments)."""
    r = api_call(dhan.quote_data, securities={"NSE_EQ": [int(s["security_id"]) for s in universe]}, retries=3)
    data = r.get("data") if isinstance(r, dict) else None
    data = (data or {}).get("data", data) or {}  # dhanhq wraps the payload in "data" twice
    return quote_changes(data.get("NSE_EQ") or {}, universe)


def _candle_results(universe: list[dict]) -> list[dict]:
    """The universe one stock at a time from 15-min candles (~30 s): previous close = the last trade."""
    results = []
    for stock in universe:
        try:
            df = _fetch_any_stock_candles(stock["security_id"], interval=15, retries=3)
            data = _candles_to_daily_change(df)
            if data is not None:
                results.append({
                    "name":        stock["name"],
                    "security_id": stock["security_id"],
                    "data":        data,
                })
        except Exception as e:
            print(f"  [top_stocks] {stock['name']} error: {e}")
        time.sleep(_PAUSE_SECONDS)
    return results


def _fetch_top_stocks(top_n: int = TOP_N) -> tuple[list[dict], list[dict], dict]:
    """
    Rank all NIFTY 50 stocks by today's % change vs the previous close.
    Returns (top_gainers, top_losers, meta); meta = {"fetched", "universe", "updated", "synced"}.

    In market hours one bulk quote call prices all 50; outside them (the closing ranking, a start
    after hours), or if the quotes come back short, the 15-min candles, stock by stock.

    The DB list (what the trading engine scans) is only replaced when at least MIN_COVERAGE
    stocks loaded, and a stock already on it stays while it ranks within KEEP_RANK on its
    side, so a #5/#6 swap of 0.01% doesn't churn the engine's universe every 5 minutes.
    """
    from db import get_active_top_stocks

    universe = nifty50_stocks()
    results = []
    if is_market_open():
        try:
            results = _quote_results(universe)
        except Exception as e:
            print(f"  [top_stocks] bulk quote error: {e}")
        if len(results) < MIN_COVERAGE:
            print(f"  [top_stocks] bulk quote priced {len(results)}/{len(universe)} — using candles")
            results = _candle_results(universe)
    else:
        results = _candle_results(universe)

    gainers = sorted(
        [r for r in results if r["data"]["change_pct"] >= 0],
        key=lambda x: x["data"]["change_pct"],
        reverse=True,
    )
    losers = sorted(
        [r for r in results if r["data"]["change_pct"] < 0],
        key=lambda x: x["data"]["change_pct"],
    )

    top_gainers = gainers[:top_n]
    top_losers  = losers[:top_n]
    meta = {"fetched": len(results), "universe": len(universe),
            "updated": now_ist().strftime("%H:%M:%S"), "synced": False}

    if len(results) < MIN_COVERAGE:
        print(f"  [top_stocks] only {len(results)}/{len(universe)} loaded — keeping the previous list")
        return top_gainers, top_losers, meta

    # Persist to DB with hysteresis: keep current members still within KEEP_RANK on their side
    try:
        current = {s["security_id"] for s in get_active_top_stocks()}
        keep_g = [r for r in gainers[top_n:KEEP_RANK] if r["security_id"] in current]
        keep_l = [r for r in losers[top_n:KEEP_RANK] if r["security_id"] in current]
        sync_top_stocks(
            gainers=[{"name": r["name"], "security_id": r["security_id"]} for r in top_gainers + keep_g],
            losers =[{"name": r["name"], "security_id": r["security_id"]} for r in top_losers + keep_l],
        )
        meta["synced"] = True
    except Exception as e:
        print(f"  [top_stocks] DB sync error: {e}")

    return top_gainers, top_losers, meta


def _show_stock_chart_modal(name: str, security_id: str):
    """Open a modal with the 25-min candle chart (5 days) for a stock."""
    with ui.dialog().props("persistent").classes("!max-w-5xl w-full") as dlg:
        dlg.open()
        with ui.card().classes("w-full !rounded-2xl overflow-hidden").style(
            "min-width:min(900px,95vw); padding:0; gap:0;"
        ):
            with ui.row().classes("items-center w-full px-5 py-3 border-b border-gray-200").style("gap:8px;"):
                ui.icon("candlestick_chart", size="20px").classes("text-emerald-500")
                ui.label(name).classes("text-sm font-bold text-gray-800")
                ui.label("25-min · 5 Days").classes("text-xs text-gray-400 font-medium")
                ui.space()
                ui.button(icon="close", on_click=dlg.close).props("flat round dense").classes("text-gray-400")

            chart_area = ui.element("div").classes("w-full p-4")
            with chart_area:
                ui.spinner("dots", size="lg").classes("mx-auto my-8 block")

    async def _load():
        candles = await asyncio.get_event_loop().run_in_executor(
            None, lambda: _fetch_any_stock_candles(security_id, interval=25)
        )
        chart_area.clear()
        with chart_area:
            if candles is None or candles.empty:
                ui.label("No data available.").classes(
                    "text-gray-400 italic text-sm p-4"
                )
                return

            chart_id = f"tv_{uuid.uuid4().hex[:10]}"
            ui.html(
                f'<div class="at-chart-wrap"><div id="{chart_id}" style="width:100%;height:420px;"></div></div>',
                sanitize=False,
            )

            ohlc = _candles_to_tv(candles)
            opts = dict(_BASE_OPTS)
            opts["height"] = 420

            js = f"""
            (function initModal_{chart_id}() {{
                var el = document.getElementById('{chart_id}');
                if (!el) {{ setTimeout(initModal_{chart_id}, 100); return; }}
                var opts = {json.dumps(opts)};
                opts.width = _tvElWidth(el);
                var chart = LightweightCharts.createChart(el, opts);
                window._tvChartInstances = window._tvChartInstances || [];
                window._tvThemeOpts = window._tvThemeOpts || function(l) {{ return l ? {{layout:{{background:{{type:'solid',color:'#f5f7fa'}},textColor:'#3d4a57'}},grid:{{vertLines:{{color:'#e0e4ea'}},horzLines:{{color:'#e0e4ea'}}}}}} : {{layout:{{background:{{type:'solid',color:'#0a0d10'}},textColor:'#8a97a3'}},grid:{{vertLines:{{color:'#1a2128'}},horzLines:{{color:'#1a2128'}}}}}}; }};
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

    asyncio.ensure_future(_load())


def _stock_card(entry: dict):
    """Render a single stock card."""
    name        = entry["name"]
    security_id = entry["security_id"]
    d           = entry["data"]

    is_green     = d["is_green"]
    sign         = "+" if d["change"] >= 0 else ""
    price_cls    = "text-green-700 font-bold" if is_green else "text-red-700 font-bold"
    change_cls   = "text-green-600" if is_green else "text-red-600"
    dot_cls      = "bg-green-500" if is_green else "bg-red-500"
    border_color = "#4ade80" if is_green else "#f87171"
    bg_color     = "rgba(0,208,132,0.08)" if is_green else "rgba(255,77,94,0.08)"

    def on_click(n=name, sid=security_id):
        _show_stock_chart_modal(n, sid)

    with ui.card().classes(
        "rounded-xl shadow-sm cursor-pointer transition-all hover:shadow-md"
    ).style(
        f"border: 1px solid {border_color} !important; background: {bg_color}; padding: 14px 16px;"
    ).on("click", on_click):
        with ui.row().classes("items-center gap-2 mb-2"):
            ui.element("div").classes(
                f"w-2 h-2 rounded-full {dot_cls} flex-shrink-0"
            )
            ui.label(name).classes(
                "text-xs font-bold text-gray-600 uppercase tracking-widest truncate"
            )

        ui.label(f"₹{d['current']:,.2f}").classes(
            f"text-lg {price_cls} leading-tight"
        )

        with ui.row().classes("items-center gap-2 mt-1"):
            ui.label(f"{sign}{d['change_pct']:.2f}%").classes(
                f"text-sm font-bold {change_cls}"
            )
            ui.label(f"({sign}{d['change']:,.2f})").classes(
                "text-xs text-gray-400"
            )

        with ui.element("div").classes("mt-2 pt-2 border-t border-gray-200"):
            with ui.row().classes("gap-3 text-[10px] text-gray-500"):
                ui.label(f"O: {d['open']:,.2f}")
                ui.label(f"H: {d['high']:,.2f}")
                ui.label(f"L: {d['low']:,.2f}")

        ui.label("Click to view chart →").classes(
            "text-[9px] text-gray-400 mt-2 text-right"
        )


def render_top_stocks_tab(container):
    """Render the Top Stocks scanner page."""
    with container:
        with ui.row().classes("items-center gap-2 mb-1"):
            ui.icon("rocket_launch", size="24px").classes("text-amber-500")
            ui.label("Top NIFTY 50 Stocks").classes("text-xl font-bold text-gray-800")
        ui.label(
            "Top 5 gainers & top 5 losers — ranked by % change vs previous close · click a card for 25-min chart (5 days)"
        ).classes("text-xs text-gray-400 mb-4")

        content = ui.element("div").classes("w-full")
        with content:
            ui.spinner("dots", size="lg").classes("mx-auto my-8 block")

    page_client = context.client

    async def refresh():
        if page_client._deleted:
            return
        try:
            from state import _cache_get_stable, _cache_set
            # The background loop refreshes this every 5 min; reading it (ignoring the 90s
            # cache TTL) keeps the page and the engine on the same list.
            cached = _cache_get_stable("top_stocks_data")
            if not cached:
                content.clear()
                with content:
                    ui.spinner("dots", size="lg").classes("mx-auto my-8 block")
                    ui.label("Ranking all 50 NIFTY stocks (about 30 seconds)…").classes(
                        "text-gray-500 text-center w-full text-sm"
                    )
                gainers, losers, meta = await asyncio.get_event_loop().run_in_executor(
                    None, _fetch_top_stocks
                )
                cached = {"gainers": gainers, "losers": losers, "meta": meta}
                _cache_set("top_stocks_data", cached)
            gainers, losers = cached["gainers"], cached["losers"]
            meta = cached.get("meta", {})
            if page_client._deleted:
                return
            content.clear()
            with content:
                if not gainers and not losers:
                    ui.label("No data available.").classes(
                        "text-gray-400 italic text-sm"
                    )
                    return

                with ui.row().classes("items-center gap-3 mb-3"):
                    ui.label("Top Gainers").classes(
                        "text-xs font-bold text-green-600 uppercase tracking-widest"
                    )
                    ui.element("div").classes("flex-1 h-px bg-green-100")

                if gainers:
                    with ui.element("div").classes(
                        "grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-3 mb-6"
                    ):
                        for entry in gainers:
                            _stock_card(entry)
                else:
                    ui.label("No gainers today.").classes("text-gray-400 italic text-sm mb-6")

                with ui.row().classes("items-center gap-3 mb-3"):
                    ui.label("Top Losers").classes(
                        "text-xs font-bold text-red-600 uppercase tracking-widest"
                    )
                    ui.element("div").classes("flex-1 h-px bg-red-100")

                if losers:
                    with ui.element("div").classes(
                        "grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-3 mb-6"
                    ):
                        for entry in losers:
                            _stock_card(entry)
                else:
                    ui.label("No losers today.").classes("text-gray-400 italic text-sm mb-6")

                coverage = (f"Ranked {meta['fetched']} of {meta['universe']} NIFTY 50 stocks"
                            if meta else "Ranked NIFTY 50 stocks")
                if meta and not meta.get("synced"):
                    coverage += " — too few loaded, the engine kept its previous list"
                ui.label(
                    f"{coverage} · updated {meta.get('updated', now_ist().strftime('%H:%M:%S'))} IST · "
                    f"refreshes every 5 min in market hours"
                ).classes("text-xs text-gray-400 mt-2")

        except Exception:
            if not page_client._deleted:
                content.clear()
                with content:
                    ui.label("Error loading stock data.").classes("text-red-500")
            print(f"  [top_stocks] error:\n{traceback.format_exc()}")

    return refresh
