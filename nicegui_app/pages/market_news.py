"""
Market News page: fetches latest Indian market news from open RSS feeds.
"""

import asyncio
import traceback
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import urllib.request
from nicegui import ui, context

from config import now_ist

# Open RSS feeds for Indian market news (no API key required)
NEWS_FEEDS = [
    {
        "name": "Economic Times Markets",
        "url": "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
    },
    {
        "name": "Moneycontrol Markets",
        "url": "https://www.moneycontrol.com/rss/marketreports.xml",
    },
    {
        "name": "Business Standard Markets",
        "url": "https://www.business-standard.com/rss/markets-106.rss",
    },
    {
        "name": "NSE News",
        "url": "https://www1.nseindia.com/rss/newsrss.xml",
    },
]

MAX_AGE_HOURS = 48  # discard articles older than this
MAX_ARTICLES = 30   # cap total cards shown


def _fetch_feed(feed_info: dict) -> list[dict]:
    """Fetch and parse a single RSS feed. Returns list of article dicts."""
    articles = []
    try:
        req = urllib.request.Request(
            feed_info["url"],
            headers={"User-Agent": "Mozilla/5.0 (AlgoTrade RSS Reader)"},
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            raw = resp.read()
        root = ET.fromstring(raw)
        channel = root.find("channel")
        if channel is None:
            return articles

        for item in channel.findall("item"):
            title = (item.findtext("title") or "").strip()
            link  = (item.findtext("link")  or "").strip()
            desc  = (item.findtext("description") or "").strip()
            pub   = item.findtext("pubDate") or ""

            # Parse publish time
            pub_dt = None
            if pub:
                try:
                    pub_dt = parsedate_to_datetime(pub)
                    # Normalise to UTC-aware
                    if pub_dt.tzinfo is None:
                        pub_dt = pub_dt.replace(tzinfo=timezone.utc)
                except Exception:
                    pub_dt = None

            # Age filter
            if pub_dt:
                age_hours = (
                    datetime.now(timezone.utc) - pub_dt
                ).total_seconds() / 3600
                if age_hours > MAX_AGE_HOURS:
                    continue

            articles.append(
                {
                    "title": title,
                    "link": link,
                    "desc": desc,
                    "pub_dt": pub_dt,
                    "source": feed_info["name"],
                }
            )
    except Exception:
        pass  # silently skip broken feeds
    return articles


def _fetch_all_news() -> list[dict]:
    """Fetch from all feeds, de-dup by title, sort newest-first."""
    seen_titles: set[str] = set()
    all_articles: list[dict] = []

    for feed in NEWS_FEEDS:
        for art in _fetch_feed(feed):
            key = art["title"].lower()[:80]
            if key and key not in seen_titles:
                seen_titles.add(key)
                all_articles.append(art)

    # Sort: articles with timestamps first (newest → oldest), then untimed
    timed   = [a for a in all_articles if a["pub_dt"] is not None]
    untimed = [a for a in all_articles if a["pub_dt"] is None]
    timed.sort(key=lambda a: a["pub_dt"], reverse=True)

    return (timed + untimed)[:MAX_ARTICLES]


def _time_ago(pub_dt) -> str:
    if pub_dt is None:
        return "Unknown time"
    delta = datetime.now(timezone.utc) - pub_dt
    minutes = int(delta.total_seconds() / 60)
    if minutes < 1:
        return "Just now"
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h ago"
    days = hours // 24
    return f"{days}d ago"


def render_market_news_tab(container):
    with container:
        with ui.row().classes("items-center gap-2 mb-1"):
            ui.icon("newspaper", size="24px").classes("text-blue-500")
            ui.label("Market News").classes("text-xl font-bold text-gray-800")
        ui.label("Latest Indian market headlines — updated on each refresh").classes(
            "text-xs text-gray-400 mb-4"
        )
        content = ui.element("div").classes("w-full")
        with content:
            ui.spinner("dots", size="lg").classes("mx-auto my-8 block")

    page_client = context.client

    async def refresh():
        if page_client._deleted:
            return
        try:
            articles = await asyncio.get_event_loop().run_in_executor(
                None, _fetch_all_news
            )
            if page_client._deleted:
                return
            content.clear()
            with content:
                if not articles:
                    ui.label("No recent news found. Try again later.").classes(
                        "text-gray-400 my-8"
                    )
                else:
                    with ui.element("div").classes("news-grid"):
                        for art in articles:
                            _news_card(art)
                ui.label(
                    f"Last updated: {now_ist().strftime('%H:%M:%S')} IST"
                ).classes("text-xs text-gray-400 mt-4")
        except Exception:
            if not page_client._deleted:
                content.clear()
                with content:
                    ui.label("Error loading news.").classes("text-red-500")
            print(f"  [market_news] error:\n{traceback.format_exc()}")

    return refresh


def _news_card(art: dict):
    title   = art["title"] or "No title"
    source  = art["source"]
    desc    = art["desc"]
    link    = art["link"]
    ago     = _time_ago(art["pub_dt"])

    # Truncate long descriptions
    if len(desc) > 180:
        desc = desc[:177].rsplit(" ", 1)[0] + "…"
    # Strip basic HTML tags from description
    import re
    desc = re.sub(r"<[^>]+>", "", desc).strip()

    with ui.card().classes(
        "rounded-xl shadow-sm bg-white border border-gray-100 p-4 hover:shadow-md transition-shadow cursor-pointer"
    ).props("flat"):
        # Source + time row
        with ui.row().classes("items-center gap-2 mb-2"):
            ui.element("div").classes("w-1.5 h-1.5 rounded-full bg-blue-500")
            ui.label(source).classes(
                "text-[10px] font-bold text-blue-600 uppercase tracking-widest"
            )
            ui.space()
            ui.label(ago).classes("text-[10px] text-gray-400")

        # Title — clickable link
        if link:
            ui.link(title, target=link, new_tab=True).classes(
                "text-sm font-semibold text-gray-800 leading-snug hover:text-blue-600 no-underline"
            )
        else:
            ui.label(title).classes(
                "text-sm font-semibold text-gray-800 leading-snug"
            )

        # Description
        if desc:
            ui.label(desc).classes("text-xs text-gray-500 mt-1.5 leading-relaxed")
