import pandas as pd
import talib

# import pandas_ta as ta
import xlwings as xw

# import winsound
from dhan_login import tsl, reciever_chat_id as receiver_chat_id, bot_token
import pdb
import time as tim
from datetime import datetime, time
from zoneinfo import ZoneInfo
from telegram import send_alert_to_all
from dhan_watchlist import watchlist
from send_email import send_algo_report
from dhan_services.market_opennings import market_session_status
from dhan_services.excel_reporter import ExcelReporter
from dhan_services.orderbook_template import init_orderbook
from dhan_services.orderbook_template import get_empty_order
from strategies.indicators import apply_indicators, should_buy
from dhan_services.execution import execute_buy_entry, check_and_exit_position


excel = ExcelReporter()
orderbook = init_orderbook(watchlist)
completed_orders = []
last_status = None
reentry = "yes"

current_time = datetime.now(ZoneInfo("Asia/Kolkata")).time()
time_message = datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%Y-%m-%d (%A)")
message = f"[{time_message}]\n Welcome to algo trading"
send_alert_to_all(message, receiver_chat_id, bot_token)

last_status = None
while True:

    status, now, ref_time = market_session_status()

    if status != last_status:
        if status == "PRE_MARKET":
            print(f"⏳ Market not open yet. Current time: {now.strftime('%H:%M:%S')}")
        elif status == "OPEN":
            print(f"✅ Market is OPEN. Current time: {now.strftime('%H:%M:%S')}")
        elif status == "POST_MARKET":
            print(f"🔴 Market is CLOSED. Current time: {now.strftime('%H:%M:%S')}")

        last_status = status

    if status == "PRE_MARKET":
        sleep_seconds = min((ref_time - now).seconds, 60)
        tim.sleep(sleep_seconds)
        continue

    if status == "POST_MARKET":
        print("💾 Workbook saved successfully (AlgoTrade.xlsx)")
        break

    all_ltp = tsl.get_ltp_data(names=watchlist)
    for name in watchlist:
        excel.update_live_orders(orderbook)
        excel.update_completed_orders(completed_orders)

        current_time = datetime.now()
        print(f"Scanning        {name} {current_time}")

        try:
            chart = tsl.get_historical_data(
                tradingsymbol=name, exchange="NSE", timeframe="5"
            )
            chart = apply_indicators(chart)
            cc = chart.iloc[-2]

        except Exception as e:
            print(e)
            raise Exception("Dont know") from e

        if should_buy(cc, orderbook[name]):
            print("BUY ", name, "\t")

            margin_avialable = tsl.get_balance()
            margin_required = cc["close"] / 4.5

            # if margin_avialable < margin_required:
            #     print(
            #         f"Less margin, not taking order : margin_avialable is {margin_avialable} and margin_required is {margin_required} for {name}"
            #     )
            #     continue

            try:

                order = execute_buy_entry(
                    tsl=tsl,
                    name=name,
                    cc=cc,
                    orderbook=orderbook,
                    current_time=current_time,
                )

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
                            orderbook[name] = get_empty_order()
                    except Exception as e:
                        print(e)
                        pdb.set_trace(header="error in sl_hit")

                if tg_hit:

                    try:
                        # tsl.cancel_order(OrderID=orderbook[name]["sl_orderid"])
                        # tim.sleep(2)
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
                            orderbook[name] = get_empty_order()

                        # winsound.Beep(1500, 10000)

                    except Exception as e:
                        print(e)
                        pdb.set_trace(header="error in tg_hit")
