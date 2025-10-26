import pandas as pd
import talib

# import pandas_ta as ta
import xlwings as xw
import winsound
from dhan_login import tsl, reciever_chat_id as receiver_chat_id, bot_token
import pdb
import time
from datetime import datetime, time
from zoneinfo import ZoneInfo
from telegram import send_alert_to_all
from dhan_watchlist import watchlist


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

current_time = datetime.now(ZoneInfo("Asia/Kolkata")).time()
time_message = datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%Y-%m-%d (%A)")
message = f"[{time_message}]\n Algo is waiting to be started"
send_alert_to_all(message, receiver_chat_id, bot_token)

while True:

    print("starting while Loop \n\n")

    # Market open and close times in IST
    market_open = time(9, 15)
    market_close = time(15, 15)

    if current_time < market_open:
        print(f"Market not open yet ({current_time}), waiting until 09:15 IST")
        time.sleep(1)
        continue

    if current_time > market_close:
        # Cancel all pending (simulated) orders
        # order_details = tsl.cancel_all_orders()  # only if using real API
        print(f"Market closed ({current_time}) — ending trading session.")
        message = (
            f"[{time_message}]\n Algo wont be executed today as the markets are closed"
        )
        send_alert_to_all(message, receiver_chat_id, bot_token)
        break

    all_ltp = tsl.get_ltp_data(names=watchlist)
    for name in watchlist:

        orderbook_df = pd.DataFrame(orderbook).T
        live_Trading.range("A1").value = orderbook_df

        completed_orders_df = pd.DataFrame(completed_orders)
        completed_orders_sheet.range("A1").value = completed_orders_df

        current_time = datetime.datetime.now()
        print(f"Scanning        {name} {current_time}")

        try:
            chart = tsl.get_historical_data(
                tradingsymbol=name, exchange="NSE", timeframe="5"
            )
            chart["rsi"] = talib.RSI(chart["close"], timeperiod=14)
            cc = chart.iloc[-2]

            # buy entry conditions
            bc1 = cc["rsi"] > 45
            bc2 = orderbook[name]["traded"] is None
        except Exception as e:
            print(e)
            continue

        if bc1 and bc2:
            print("buy ", name, "\t")

            margin_avialable = tsl.get_balance()
            margin_required = cc["close"] / 4.5

            # if margin_avialable < margin_required:
            #     print(
            #         f"Less margin, not taking order : margin_avialable is {margin_avialable} and margin_required is {margin_required} for {name}"
            #     )
            #     continue

            orderbook[name]["name"] = name
            orderbook[name]["date"] = str(current_time.date())
            orderbook[name]["entry_time"] = str(current_time.time())[:8]
            orderbook[name]["buy_sell"] = "BUY"
            orderbook[name]["qty"] = 1

            try:

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
                orderbook[name]["entry_price"] = cc["close"]

                orderbook[name]["tg"] = round(
                    orderbook[name]["entry_price"] * 1.002, 1
                )  # 1.01
                orderbook[name]["sl"] = round(
                    orderbook[name]["entry_price"] * 0.998, 1
                )  # 99
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
                orderbook[name]["sl_orderid"] = "1234"
                orderbook[name]["traded"] = "yes"

                message = "\n".join(
                    f"'{key}': {repr(value)}" for key, value in orderbook[name].items()
                )
                message = f"Entry_done {name} \n\n {message}"
                send_alert_to_all(message, receiver_chat_id, bot_token)

            except Exception as e:
                print(e)
                pdb.set_trace(header="error in entry order")

        if orderbook[name]["traded"] == "yes":
            bought = orderbook[name]["buy_sell"] == "BUY"

            if bought:

                try:
                    ltp = all_ltp[name]
                    # sl_hit = (
                    #     tsl.get_order_status(orderid=orderbook[name]["sl_orderid"])
                    #     == "TRADED"
                    # )
                    sl_hit = ltp < orderbook[name]["sl"]
                    tg_hit = ltp > orderbook[name]["tg"]
                except Exception as e:
                    print(e)
                    pdb.set_trace(header="error in sl order cheking")

                if sl_hit:

                    try:
                        orderbook[name]["exit_time"] = str(current_time.time())[:8]
                        # orderbook[name]["exit_price"] = tsl.get_executed_price(
                        #     orderid=orderbook[name]["sl_orderid"]
                        # )
                        orderbook[name]["exit_price"] = ltp
                        orderbook[name]["pnl"] = round(
                            (
                                orderbook[name]["exit_price"]
                                - orderbook[name]["entry_price"]
                            )
                            * orderbook[name]["qty"],
                            1,
                        )
                        orderbook[name]["remark"] = "Bought_SL_hit"

                        message = "\n".join(
                            f"'{key}': {repr(value)}"
                            for key, value in orderbook[name].items()
                        )
                        message = f"SL_HIT {name} \n\n {message}"
                        send_alert_to_all(
                            message,
                            receiver_chat_id,
                            bot_token,
                        )

                        if reentry == "yes":
                            completed_orders.append(orderbook[name])
                            orderbook[name] = None
                    except Exception as e:
                        print(e)
                        pdb.set_trace(header="error in sl_hit")

                if tg_hit:

                    try:
                        # tsl.cancel_order(OrderID=orderbook[name]["sl_orderid"])
                        # time.sleep(2)
                        # square_off_buy_order = tsl.order_placement(
                        #     tradingsymbol=orderbook[name]["name"],
                        #     exchange="NSE",
                        #     quantity=orderbook[name]["qty"],
                        #     price=0,
                        #     trigger_price=0,
                        #     order_type="MARKET",
                        #     transaction_type="SELL",
                        #     trade_type="MIS",
                        # )

                        orderbook[name]["exit_time"] = str(current_time.time())[:8]
                        # orderbook[name]["exit_price"] = tsl.get_executed_price(
                        #     orderid=square_off_buy_order
                        # )
                        orderbook[name]["exit_price"] = ltp
                        orderbook[name]["pnl"] = (
                            orderbook[name]["exit_price"]
                            - orderbook[name]["entry_price"]
                        ) * orderbook[name]["qty"]
                        orderbook[name]["remark"] = "Bought_TG_hit"

                        message = "\n".join(
                            f"'{key}': {repr(value)}"
                            for key, value in orderbook[name].items()
                        )
                        message = f"TG_HIT {name} \n\n {message}"
                        send_alert_to_all(
                            message,
                            receiver_chat_id,
                            bot_token,
                        )

                        if reentry == "yes":
                            completed_orders.append(orderbook[name])
                            orderbook[name] = None

                        # winsound.Beep(1500, 10000)

                    except Exception as e:
                        print(e)
                        pdb.set_trace(header="error in tg_hit")
