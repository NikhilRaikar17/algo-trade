# get_instruments.py
from zerodha_kite.kite_client import get_kite_client
import pandas as pd

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
    symbol = input("Enter the trading symbol (e.g., RELIANCE, NIFTY24OCTFUT): ").strip().upper()
    exchange = input("Enter the exchange (e.g., NSE, BSE, NFO): ").strip().upper()

    try:
        df = pd.DataFrame(kite.instruments(exchange))

        # Quick search ignoring case
        match = df[df["tradingsymbol"].str.upper() == symbol]

        if not match.empty:
            print("✅ Instrument Found:")
            print(
                match[
                    ["instrument_token", "tradingsymbol", "exchange", "name", "segment", "expiry"]
                ].to_string(index=False)
            )
        else:
            # Debugging help
            print(f"⚠️ Not found: {symbol} in {exchange}")
            print("🔍 Did you mean one of these?")
            print(
                df[df["tradingsymbol"].str.contains(symbol[:5], case=False)][
                    ["tradingsymbol", "expiry"]
                ].head(10)
            )
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
