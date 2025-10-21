from dhan_login import tsl
import pdb

watchlist = ["ADANIPORTS", "SBIN", "NIFTY", "CIPLA"]
bot_token = "8360379748:AAGigp1SlPb1O-ioRutvRu-ee9ZJaqs4WO4"
reciever_chat_id = ["8272803637", "1623717769"]
for name in watchlist:
    print(f"Getting data for {name}")
    charts = tsl.get_historical_data(tradingsymbol=name, exchange="NSE", timeframe="5")
    closing_price = charts['close'].iloc[-1]
    message = (f"This is an auto generated bot message for {name}"
            f"The closing price of the stock for tody is {closing_price}")
    for rec in reciever_chat_id:
        tsl.send_telegram_alert(message=message, receiver_chat_id=rec, bot_token=bot_token)