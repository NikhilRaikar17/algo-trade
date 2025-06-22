import os
from dotenv import load_dotenv, set_key
from kiteconnect import KiteConnect

ENV_FILE = os.path.join(os.path.dirname(__file__), ".env")
load_dotenv(dotenv_path=ENV_FILE, override=True)

API_KEY = os.getenv("KITE_API_KEY")
API_SECRET = os.getenv("KITE_API_SECRET")

def get_login_url():
    kite = KiteConnect(api_key=API_KEY)
    return kite.login_url()

def generate_access_token() -> str:
    kite = KiteConnect(api_key=API_KEY)
    print("🔐 Login URL:", kite.login_url())
    request_token = input("📥 Paste the request_token from URL: ").strip()
    data = kite.generate_session(request_token, api_secret=API_SECRET)

    access_token = data["access_token"]
    set_key(ENV_FILE, "KITE_ACCESS_TOKEN", access_token)
    print("✅ Access token saved to .env")
    return access_token
