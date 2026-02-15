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


def check_market_open(last_status: bool) -> bool:
    status, now, ref_time = market_session_status()

    if status != last_status:
        if status == "PRE_MARKET":
            print(f"⏳ Market not open yet. Current time: {now.strftime('%H:%M:%S')}")
        elif status == "OPEN":
            print(f"✅ Market is OPEN. Current time: {now.strftime('%H:%M:%S')}")
        elif status == "POST_MARKET":
            print(f"🔴 Market is CLOSED. Current time: {now.strftime('%H:%M:%S')}")

        last_status = status

    if status == "PRE_MARKET":
        sleep_seconds = min((ref_time - now).seconds, 60)
        time.sleep(sleep_seconds)
        return True

    if status == "POST_MARKET":
        print("💾 Workbook saved successfully (AlgoTrade.xlsx)")
        return False
