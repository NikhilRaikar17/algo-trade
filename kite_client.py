import os
from kiteconnect import KiteConnect
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("KITE_API_KEY")
ACCESS_TOKEN = os.getenv("KITE_ACCESS_TOKEN")


# def get_kite_client() -> KiteConnect:
#     kite = KiteConnect(api_key=API_KEY)
#     kite.set_access_token(ACCESS_TOKEN)
#     return kite

