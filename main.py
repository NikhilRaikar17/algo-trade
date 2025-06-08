from kite_client import kite
import datetime

# 1. Get profile
try:
    profile = kite.profile()
    print("Logged in as:", profile["user_name"])
except Exception as e:
    print("Token may be expired or invalid:", e)
    exit()

# 2. Historical data (example: INFY)
instrument_token = 738561
from_date = datetime.datetime.now() - datetime.timedelta(days=5)
to_date = datetime.datetime.now()

try:
    candles = kite.historical_data(
        instrument_token=instrument_token,
        from_date=from_date,
        to_date=to_date,
        interval="5minute"
    )
    print(f"Fetched {len(candles)} candles")
    for c in candles[:5]:
        print(c)
except Exception as e:
    print("Error fetching historical data:", e)
