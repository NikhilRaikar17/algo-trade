from datetime import datetime, time
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


def market_session_status():
    now = datetime.now(IST)

    market_open = datetime.combine(now.date(), time(9, 15), tzinfo=IST)
    market_close = datetime.combine(now.date(), time(15, 15), tzinfo=IST)

    if now < market_open:
        return "PRE_MARKET", now, market_open

    if now > market_close:
        return "POST_MARKET", now, market_close

    return "OPEN", now, market_close
