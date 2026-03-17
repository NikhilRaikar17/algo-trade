import os

from Dhan_Tradehull import Tradehull
from dotenv import load_dotenv

ENV_FILE = os.path.join(os.path.dirname(__file__), "...", ".env")
ENV_FILE = os.path.abspath(ENV_FILE)
load_dotenv(dotenv_path=ENV_FILE, override=True)


def get_conf_obj():
    try:
        client_code = os.getenv("DHAN_CLIENT_CODE")
        token_id = os.getenv("DHAN_TOKEN_ID")
        bot_token = os.getenv("DHAN_BOT_TOKEN")
        paper_trading = os.getenv("DHAN_PAPER_TRADING")
        if not client_code or not token_id or not paper_trading or not bot_token:
            raise Exception("Cannot continue as the envs are not loded")
        tsl = Tradehull(client_code, token_id)
        if not tsl:
            raise Exception("Tradehull is not wokring properly")
        print("Logged in successfully and am able to connect to dhan")
        reciever_chat_id = ["8272803637", "1623717769"]
        return tsl, reciever_chat_id, paper_trading, bot_token
    except Exception as e:
        raise e from e


tsl, reciever_chat_id, PAPER_TARDING, bot_token = get_conf_obj()
