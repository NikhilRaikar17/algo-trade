"""
Global market data feed using yfinance.

Fetches prices for 13 global indices, commodities, and crypto every 60 s.
Writes results to state._global_prices via set_global_price().

Usage (called once from main.py):
    asyncio.create_task(start_global_feed())
"""
import asyncio

import yfinance as yf

from state import set_global_price, get_all_global_prices  # noqa: F401 (re-exported)

# Symbol → (display name, currency symbol, flag emoji)
SYMBOLS: dict[str, tuple[str, str, str]] = {
    "^GSPC":     ("S&P 500",       "USD", "🇺🇸"),
    "^IXIC":     ("NASDAQ",        "USD", "🇺🇸"),
    "^DJI":      ("Dow Jones",     "USD", "🇺🇸"),
    "^FTSE":     ("FTSE 100",      "GBP", "🇬🇧"),
    "^GDAXI":    ("DAX",           "EUR", "🇩🇪"),
    "^FCHI":     ("CAC 40",        "EUR", "🇫🇷"),
    "^N225":     ("Nikkei 225",    "JPY", "🇯🇵"),
    "^HSI":      ("Hang Seng",     "HKD", "🇭🇰"),
    "000001.SS": ("Shanghai Comp", "CNY", "🇨🇳"),
    "GC=F":      ("Gold",          "USD", "🥇"),
    "CL=F":      ("Crude Oil",     "USD", "🛢️"),
    "BTC-USD":   ("Bitcoin",       "USD", "₿"),
    "ETH-USD":   ("Ethereum",      "USD", "Ξ"),
}

_TICKERS = " ".join(SYMBOLS.keys())


def _fetch_and_store() -> None:
    """Download latest prices via yfinance and write to state._global_prices."""
    try:
        df = yf.download(_TICKERS, period="2d", interval="1d",
                         group_by="ticker", auto_adjust=True, progress=False)
    except Exception as exc:
        print(f"  [global_feed] download failed: {exc}")
        return

    for symbol, (name, currency, flag) in SYMBOLS.items():
        try:
            close_col = (symbol, "Close")
            if close_col not in df.columns:
                continue
            closes = df[close_col].dropna()
            if len(closes) < 2:
                continue
            prev_close = float(closes.iloc[-2])
            price = float(closes.iloc[-1])
            if prev_close == 0:
                continue
            change_pct = round((price - prev_close) / prev_close * 100, 2)
            set_global_price(symbol, {
                "name": name,
                "price": round(price, 2),
                "change_pct": change_pct,
                "currency": currency,
                "flag": flag,
            })
        except Exception as exc:
            print(f"  [global_feed] skipping {symbol}: {exc}")


async def start_global_feed() -> None:
    """
    Background loop: fetch global prices immediately, then every 60 s.
    Runs forever — errors within a cycle are swallowed; the loop continues.
    """
    while True:
        await asyncio.get_running_loop().run_in_executor(None, _fetch_and_store)
        await asyncio.sleep(60)
