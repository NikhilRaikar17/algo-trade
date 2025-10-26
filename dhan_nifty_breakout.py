import pdb
import time
import datetime
import traceback
from Dhan_Tradehull import Tradehull
import pandas as pd
from pprint import pprint
import talib

# import pandas_ta as ta
import xlwings as xw
import winsound
from dhan_login import tsl, reciever_chat_id as receiver_chat_id, bot_token
import pdb


# pre_market_watchlist        = ['ASIANPAINT', 'BAJAJ-AUTO', 'BERGEPAINT', 'BEL', 'BOSCHLTD', 'BRITANNIA', 'COALINDIA', 'COLPAL', 'DABUR', 'DIVISLAB', 'EICHERMOT', 'GODREJCP', 'HCLTECH', 'HDFCBANK', 'HAVELLS', 'HEROMOTOCO', 'HAL', 'HINDUNILVR', 'ITC', 'IRCTC', 'INFY', 'LTIM', 'MARICO', 'MARUTI', 'NESTLEIND', 'PIDILITIND', 'TCS', 'TECHM', 'WIPRO']
# watchlist                   = []

# for name in pre_market_watchlist:

# 	print("Pre market scanning ", name)
# 	day_chart = tsl.get_historical_data(tradingsymbol = name,exchange = 'NSE',timeframe="DAY")
# 	day_chart['upperband'], day_chart['middleband'], day_chart['lowerband'] = talib.BBANDS(day_chart['close'], timeperiod=20, nbdevup=2, nbdevdn=2, matype=0)


# 	last_day_candle = day_chart.iloc[-1]

# 	upper_breakout = last_day_candle['high'] > last_day_candle['upperband']
# 	lower_breakout = last_day_candle['low'] < last_day_candle['lowerband']

# 	if upper_breakout or lower_breakout:
# 		watchlist.append(name)
# 		print(f"\t selected {name} for trading")
# 		pdb.set_trace()


# print(watchlist)
# # pdb.set_trace()


watchlist = [
    "BEL",
    "BOSCHLTD",
    "COLPAL",
    "HCLTECH",
    "HDFCBANK",
    "HAVELLS",
    "HAL",
    "ITC",
    "IRCTC",
    "INFY",
    "LTIM",
    "MARICO",
    "MARUTI",
    "NESTLEIND",
    "PIDILITIND",
    "TCS",
    "TECHM",
    "WIPRO",
]


single_order = {
    "name": None,
    "date": None,
    "entry_time": None,
    "entry_price": None,
    "buy_sell": None,
    "qty": None,
    "sl": None,
    "exit_time": None,
    "exit_price": None,
    "pnl": None,
    "remark": None,
    "traded": None,
}
orderbook = {}
wb = xw.Book("Live Trade Data.xlsx")
live_Trading = wb.sheets["Live_Trading"]
completed_orders_sheet = wb.sheets["completed_orders"]
reentry = "yes"  # "yes/no"
completed_orders = []


live_Trading.range("A2:Z100").value = None
completed_orders_sheet.range("A2:Z100").value = None

for name in watchlist:
    orderbook[name] = single_order.copy()


# while True:

#     print("starting while Loop \n\n")

#     current_time = datetime.datetime.now().time()
#     if current_time < datetime.time(13, 55):
#         print(f"Wait for market to start", current_time)
#         time.sleep(1)
#         continue

#     if current_time > datetime.time(15, 15):
#         order_details = tsl.cancel_all_orders()
#         print(
#             f"Market over Closing all trades !! Bye Bye See you Tomorrow", current_time
#         )
#         pdb.set_trace()
#         break

#     all_ltp = tsl.get_ltp_data(names=watchlist)
#     for name in watchlist:

#         orderbook_df = pd.DataFrame(orderbook).T
#         live_Trading.range("A1").value = orderbook_df

#         completed_orders_df = pd.DataFrame(completed_orders)
#         completed_orders_sheet.range("A1").value = completed_orders_df

#         current_time = datetime.datetime.now()
#         print(f"Scanning        {name} {current_time}")

#         try:
#             chart = tsl.get_historical_data(
#                 tradingsymbol=name, exchange="NSE", timeframe="5"
#             )
#             chart["rsi"] = talib.RSI(chart["close"], timeperiod=14)
#             cc = chart.iloc[-2]

#             # buy entry conditions
#             bc1 = cc["rsi"] > 45
#             bc2 = orderbook[name]["traded"] is None
#         except Exception as e:
#             print(e)
#             continue

#         if bc1 and bc2:
#             print("buy ", name, "\t")

#             margin_avialable = tsl.get_balance()
#             margin_required = cc["close"] / 4.5

#             if margin_avialable < margin_required:
#                 print(
#                     f"Less margin, not taking order : margin_avialable is {margin_avialable} and margin_required is {margin_required} for {name}"
#                 )
#                 continue

#             orderbook[name]["name"] = name
#             orderbook[name]["date"] = str(current_time.date())
#             orderbook[name]["entry_time"] = str(current_time.time())[:8]
#             orderbook[name]["buy_sell"] = "BUY"
#             orderbook[name]["qty"] = 1

#             try:

#                 # entry_orderid = tsl.order_placement(
#                 #     tradingsymbol=name,
#                 #     exchange="NSE",
#                 #     quantity=orderbook[name]["qty"],
#                 #     price=0,
#                 #     trigger_price=0,
#                 #     order_type="MARKET",
#                 #     transaction_type="BUY",
#                 #     trade_type="MIS",
#                 # )
#                 orderbook[name]["entry_orderid"] = "1234"
#                 # orderbook[name]["entry_price"] = tsl.get_executed_price(
#                 #     orderid=orderbook[name]["entry_orderid"]
#                 # )
#                 orderbook[name]["entry_price"] = "1"

#                 orderbook[name]["tg"] = round(
#                     orderbook[name]["entry_price"] * 1.002, 1
#                 )  # 1.01
#                 orderbook[name]["sl"] = round(
#                     orderbook[name]["entry_price"] * 0.998, 1
#                 )  # 99
#                 # sl_orderid = tsl.order_placement(
#                 #     tradingsymbol=name,
#                 #     exchange="NSE",
#                 #     quantity=orderbook[name]["qty"],
#                 #     price=0,
#                 #     trigger_price=orderbook[name]["sl"],
#                 #     order_type="STOPMARKET",
#                 #     transaction_type="SELL",
#                 #     trade_type="MIS",
#                 # )
#                 orderbook[name]["sl_orderid"] = "1234"
#                 orderbook[name]["traded"] = "yes"

#                 message = "\n".join(
#                     f"'{key}': {repr(value)}" for key, value in orderbook[name].items()
#                 )
#                 message = f"Entry_done {name} \n\n {message}"
#                 for reciever in receiver_chat_id:
#                     tsl.send_telegram_alert(
#                         message=message, receiver_chat_id=reciever, bot_token=bot_token
#                     )

#             except Exception as e:
#                 print(e)
#                 pdb.set_trace(header="error in entry order")

#         if orderbook[name]["traded"] == "yes":
#             bought = orderbook[name]["buy_sell"] == "BUY"

#             if bought:

#                 try:
#                     ltp = all_ltp[name]
#                     sl_hit = (
#                         tsl.get_order_status(orderid=orderbook[name]["sl_orderid"])
#                         == "TRADED"
#                     )
#                     tg_hit = ltp > orderbook[name]["tg"]
#                 except Exception as e:
#                     print(e)
#                     pdb.set_trace(header="error in sl order cheking")

#                 if sl_hit:

#                     try:
#                         orderbook[name]["exit_time"] = str(current_time.time())[:8]
#                         orderbook[name]["exit_price"] = tsl.get_executed_price(
#                             orderid=orderbook[name]["sl_orderid"]
#                         )
#                         orderbook[name]["pnl"] = round(
#                             (
#                                 orderbook[name]["exit_price"]
#                                 - orderbook[name]["entry_price"]
#                             )
#                             * orderbook[name]["qty"],
#                             1,
#                         )
#                         orderbook[name]["remark"] = "Bought_SL_hit"

#                         message = "\n".join(
#                             f"'{key}': {repr(value)}"
#                             for key, value in orderbook[name].items()
#                         )
#                         message = f"SL_HIT {name} \n\n {message}"
#                         tsl.send_telegram_alert(
#                             message=message,
#                             receiver_chat_id=receiver_chat_id,
#                             bot_token=bot_token,
#                         )

#                         if reentry == "yes":
#                             completed_orders.append(orderbook[name])
#                             orderbook[name] = None
#                     except Exception as e:
#                         print(e)
#                         pdb.set_trace(header="error in sl_hit")

#                 if tg_hit:

#                     try:
#                         tsl.cancel_order(OrderID=orderbook[name]["sl_orderid"])
#                         time.sleep(2)
#                         square_off_buy_order = tsl.order_placement(
#                             tradingsymbol=orderbook[name]["name"],
#                             exchange="NSE",
#                             quantity=orderbook[name]["qty"],
#                             price=0,
#                             trigger_price=0,
#                             order_type="MARKET",
#                             transaction_type="SELL",
#                             trade_type="MIS",
#                         )

#                         orderbook[name]["exit_time"] = str(current_time.time())[:8]
#                         orderbook[name]["exit_price"] = tsl.get_executed_price(
#                             orderid=square_off_buy_order
#                         )
#                         orderbook[name]["pnl"] = (
#                             orderbook[name]["exit_price"]
#                             - orderbook[name]["entry_price"]
#                         ) * orderbook[name]["qty"]
#                         orderbook[name]["remark"] = "Bought_TG_hit"

#                         message = "\n".join(
#                             f"'{key}': {repr(value)}"
#                             for key, value in orderbook[name].items()
#                         )
#                         message = f"TG_HIT {name} \n\n {message}"
#                         tsl.send_telegram_alert(
#                             message=message,
#                             receiver_chat_id=receiver_chat_id,
#                             bot_token=bot_token,
#                         )

#                         if reentry == "yes":
#                             completed_orders.append(orderbook[name])
#                             orderbook[name] = None

#                         winsound.Beep(1500, 10000)

#                     except Exception as e:
#                         print(e)
#                         pdb.set_trace(header="error in tg_hit")
