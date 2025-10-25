from Dhan_Tradehull import Tradehull
import os
from dotenv import load_dotenv

ENV_FILE = os.path.join(os.path.dirname(__file__), ".env")
load_dotenv(dotenv_path=ENV_FILE, override=True)

client_code = os.getenv("DHAN_CLIENT_CODE")
token_id = os.getenv("DHAN_TOKEN_ID")
bot_token = os.getenv("DHAN_BOT_TOKEN")
tsl = Tradehull(client_code, token_id)
