# get_instruments.py
from kite_client import get_kite_client
import pandas as pd


# Initialize Kite Connect
kite = get_kite_client()


def fetch_all():
    try:
        instruments = kite.instruments()
        df = pd.DataFrame(instruments)
        df.to_csv("all_instruments.csv", index=False)
        print("✅ All instruments saved to 'all_instruments.csv'")
    except Exception as e:
        print(f"❌ Error fetching all instruments: {e}")

def fetch_specific():
    symbol = input("Enter the trading symbol (e.g., RELIANCE): ").strip().upper()
    exchange = input("Enter the exchange (e.g., NSE, BSE): ").strip().upper()
    
    try:
        df = pd.DataFrame(kite.instruments())
        match = df[(df["tradingsymbol"] == symbol) & (df["exchange"] == exchange)]

        if not match.empty:
            print("✅ Instrument Found:")
            print(match[["instrument_token", "tradingsymbol", "exchange", "name", "segment"]].to_string(index=False))
        else:
            print("⚠️ Instrument not found. Please check symbol and exchange.")
    except Exception as e:
        print(f"❌ Error fetching specific instrument: {e}")

def main():
    print("Do you want to fetch:")
    print("1. All instruments")
    print("2. A specific instrument")
    
    choice = input("Enter 1 or 2: ").strip()

    if choice == "1":
        fetch_all()
    elif choice == "2":
        fetch_specific()
    else:
        print("❌ Invalid choice. Please enter 1 or 2.")

if __name__ == "__main__":
    main()
