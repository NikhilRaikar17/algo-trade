import os
from dotenv import load_dotenv
from kite_client import kite
from kiteconnect import KiteConnect

load_dotenv()

API_KEY = os.getenv("KITE_API_KEY")
API_SECRET = os.getenv("KITE_API_SECRET")
ENV_FILE = ".env"


def get_login_url():
    return kite.login_url()


def generate_access_token(request_token: str) -> str:
    kite = KiteConnect(api_key=API_KEY)
    data = kite.generate_session(request_token, api_secret=API_SECRET)
    access_token = data["access_token"]

    # Save to .env
    # with open(ENV_FILE, "r") as f:
    #     lines = f.readlines()
    # with open(ENV_FILE, "w") as f:
    #     for line in lines:
    #         if line.startswith("KITE_ACCESS_TOKEN="):
    #             f.write(f"KITE_ACCESS_TOKEN={access_token}\n")
    #         else:
    #             f.write(line)
    return access_token
