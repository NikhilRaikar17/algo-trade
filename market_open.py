from kite_client import get_kite_client

# Assumes `kite` is already authenticated and ready
kite = get_kite_client()

def is_market_open():
    try:
        status_list = kite.market_status()
        for exchange in status_list:
            if exchange["exchange"] == "NSE":
                return exchange["market_status"] == "open"
        return False
    except Exception as e:
        print("Error fetching market status:", e)
        return False

# Example usage
if is_market_open():
    print("✅ NSE market is open.")
else:
    print("❌ NSE market is closed.")
