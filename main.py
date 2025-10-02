from kite_client import get_kite_client
import datetime
import pandas as pd

kite = get_kite_client()

try:
    profile = kite.profile()
    print("✅ Logged in as:", profile["user_name"])
except Exception as e:
    print("❌ Token may be invalid or expired:", e)
    exit()

# Fetch data
instrument_token = 738561
from_date = datetime.datetime.now() - datetime.timedelta(days=15)
to_date = datetime.datetime.now()

try:
    candles = kite.historical_data(
        instrument_token=instrument_token,
        from_date=from_date,
        to_date=to_date,
        interval="15minute"
    )
    print(f"📊 Fetched {len(candles)} candles")
    df = pd.DataFrame(candles)
    print(df)
except Exception as e:
    print("❌ Error fetching historical data:", e)
