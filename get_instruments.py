# get_instruments.py
from kite_client import get_kite_client
import pandas as pd


# Initialize Kite Connect
kite = get_kite_client()

# Fetch all instruments
try:
    instruments = kite.instruments()
    df = pd.DataFrame(instruments)
    print(df.head())

    # Save to CSV
    df.to_csv("all_instruments.csv", index=False)
    print("Instrument list saved to all_instruments.csv")
except Exception as e:
    print(f"Error fetching instruments: {e}")
