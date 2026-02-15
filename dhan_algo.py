import pandas as pd
import talib

# import pandas_ta as ta
import xlwings as xw

# import winsound
from dhan_services.dhan_login import tsl, reciever_chat_id as receiver_chat_id, bot_token
import pdb
import time as tim
from datetime import datetime, time
from zoneinfo import ZoneInfo
from dhan_services.telegram import send_alert_to_all
from dhan_services.dhan_watchlist import watchlist
from dhan_services.send_email import send_algo_report
from dhan_services.market_opennings import market_session_status
from dhan_services.excel_reporter import ExcelReporter
from dhan_services.orderbook_template import init_orderbook
from dhan_services.orderbook_template import get_empty_order
from strategies.indicators import apply_indicators, should_buy, should_short
from dhan_services.execution import (
    execute_buy_entry,
    check_and_exit_position,
    execute_sell_entry,
)
from dhan_services.dhan_login import PAPER_TRADING


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

    # status, now, ref_time = market_session_status()

    # if status != last_status:
    #     if status == "PRE_MARKET":
    #         print(f"⏳ Market not open yet. Current time: {now.strftime('%H:%M:%S')}")
    #     elif status == "OPEN":
    #         print(f"✅ Market is OPEN. Current time: {now.strftime('%H:%M:%S')}")
    #     elif status == "POST_MARKET":
    #         print(f"🔴 Market is CLOSED. Current time: {now.strftime('%H:%M:%S')}")

    #     last_status = status

    # if status == "PRE_MARKET":
    #     sleep_seconds = min((ref_time - now).seconds, 60)
    #     tim.sleep(sleep_seconds)
    #     continue

    # if status == "POST_MARKET":
    #     print("💾 Workbook saved successfully (AlgoTrade.xlsx)")
    #     break

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
                    paper_trading=PAPER_TRADING,
                )

                message = "\n".join(
                    f"'{key}': {repr(value)}" for key, value in orderbook[name].items()
                )
                message = f"Entry_done {name} \n\n {message}"
                send_alert_to_all(message, receiver_chat_id, bot_token)

            except Exception as e:
                print(e)
                pdb.set_trace(header="error in entry order")

        elif should_short(cc, orderbook[name]):
            execute_sell_entry(
                tsl=tsl,
                name=name,
                cc=cc,
                orderbook=orderbook,
                current_time=current_time,
                paper_trading=PAPER_TRADING,
            )

        ltp = all_ltp.get(name)

        if ltp is not None:
            try:
                exit_result = check_and_exit_position(
                    tsl=tsl,
                    name=name,
                    ltp=ltp,
                    orderbook=orderbook,
                    completed_orders=completed_orders,
                    reentry=reentry,
                    paper_trading=PAPER_TRADING,
                )

                if exit_result:
                    exit_type = exit_result["exit_type"]
                    order = exit_result["order"]

                    message = "\n".join(f"'{k}': {repr(v)}" for k, v in order.items())

                    if exit_type == "SL":
                        send_alert_to_all(
                            f"SL_HIT {name}\n\n{message}",
                            receiver_chat_id,
                            bot_token,
                        )
                    elif exit_type == "TG":
                        send_alert_to_all(
                            f"TG_HIT {name}\n\n{message}",
                            receiver_chat_id,
                            bot_token,
                        )

            except Exception as e:
                print(e)
                pdb.set_trace(header="error in exit handling")
