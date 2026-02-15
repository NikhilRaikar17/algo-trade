import time
import pdb
from datetime import datetime
from zoneinfo import ZoneInfo

from dhan_services.dhan_login import (
    PAPER_TRADING,
    bot_token,
    reciever_chat_id as receiver_chat_id,
    tsl,
)
from dhan_services.dhan_watchlist import watchlist  # {symbol: security_id}
from dhan_services.excel_reporter import ExcelReporter
from dhan_services.execution import (
    check_and_exit_position,
    execute_buy_entry,
    execute_sell_entry,
)
from dhan_services.market_opennings import check_market_open
from dhan_services.orderbook_template import init_orderbook
from dhan_services.telegram import send_alert_to_all
from dhan_websockets.live_feed import LiveMarketFeed
from strategies.indicators import apply_indicators, should_buy, should_short

# ================= INIT ================= #

excel = ExcelReporter()
orderbook = init_orderbook(watchlist)
completed_orders = []
reentry = "yes"
last_status = None

ist = ZoneInfo("Asia/Kolkata")
time_message = datetime.now(ist).strftime("%Y-%m-%d (%A)")

send_alert_to_all(
    f"[{time_message}]\nWelcome to algo trading",
    receiver_chat_id,
    bot_token,
)

# ================= START WEBSOCKET ================= #

feed = LiveMarketFeed(
    client_id=tsl.client_id,
    access_token=tsl.access_token,
    watchlist=watchlist,
)
feed.start()

# ================= MAIN LOOP ================= #

while True:
    market_open = check_market_open(last_status=last_status)
    if not market_open:
        send_alert_to_all(
            f"[{time_message}]\nMarkets are closed",
            receiver_chat_id,
            bot_token,
        )
        break

    for name, security_id in watchlist.items():
        excel.update_live_orders(orderbook)
        excel.update_completed_orders(completed_orders)

        current_time = datetime.now(ist)
        print(f"Scanning {name} {current_time}")

        # ================= HISTORICAL DATA ================= #
        try:
            chart = tsl.get_historical_data(
                tradingsymbol=name,
                exchange="NSE",
                timeframe="5",
            )
            chart = apply_indicators(chart)
            cc = chart.iloc[-2]
        except Exception as e:
            print(e)
            continue

        # ================= ENTRY LOGIC ================= #
        if should_buy(cc, orderbook[name]):
            try:
                order = execute_buy_entry(
                    tsl=tsl,
                    name=name,
                    cc=cc,
                    orderbook=orderbook,
                    current_time=current_time,
                    paper_trading=PAPER_TRADING,
                )

                msg = "\n".join(f"{k}: {v}" for k, v in orderbook[name].items())
                send_alert_to_all(
                    f"BUY ENTRY {name}\n\n{msg}",
                    receiver_chat_id,
                    bot_token,
                )

            except Exception as e:
                print(e)
                pdb.set_trace()

        elif should_short(cc, orderbook[name]):
            execute_sell_entry(
                tsl=tsl,
                name=name,
                cc=cc,
                orderbook=orderbook,
                current_time=current_time,
                paper_trading=PAPER_TRADING,
            )

        # ================= EXIT LOGIC (WS LTP) ================= #
        ltp = feed.latest_ltp.get(str(security_id))
        if ltp is None:
            continue

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

                msg = "\n".join(f"{k}: {v}" for k, v in order.items())
                send_alert_to_all(
                    f"{exit_type}_HIT {name}\n\n{msg}",
                    receiver_chat_id,
                    bot_token,
                )

        except Exception as e:
            print(e)
            pdb.set_trace()

    time.sleep(1)
