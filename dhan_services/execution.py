from datetime import datetime
import time

from numpy import square
from dhan_services.orderbook_template import get_empty_order


def execute_buy_entry(
    tsl,
    name,
    cc,
    orderbook,
    current_time,
):
    """
    Executes BUY entry:
    - Places market order
    - Fetches executed price
    - Places SL order
    - Updates orderbook
    """

    order = orderbook[name]

    # ---- Basic order details ----
    order["name"] = name
    order["date"] = str(current_time.date())
    order["entry_time"] = str(current_time.time())[:8]
    order["buy_sell"] = "BUY"
    order["qty"] = 1

    # ---- Entry order ----
    entry_orderid = tsl.order_placement(
        tradingsymbol=name,
        exchange="NSE",
        quantity=order["qty"],
        price=0,
        trigger_price=0,
        order_type="MARKET",
        transaction_type="BUY",
        trade_type="MIS",
    )

    order["entry_orderid"] = entry_orderid

    # ---- Executed price ----
    order["entry_price"] = tsl.get_executed_price(orderid=entry_orderid)

    # ---- Targets & SL ----
    order["tg"] = round(order["entry_price"] * 1.002, 1)
    order["sl"] = round(order["entry_price"] * 0.998, 1)

    # ---- SL order ----
    sl_orderid = tsl.order_placement(
        tradingsymbol=name,
        exchange="NSE",
        quantity=order["qty"],
        price=0,
        trigger_price=order["sl"],
        order_type="STOPMARKET",
        transaction_type="SELL",
        trade_type="MIS",
    )

    order["sl_orderid"] = sl_orderid
    order["traded"] = "yes"

    return order


def check_and_exit_position(
    tsl,
    name,
    ltp,
    orderbook,
    completed_orders,
    reentry,
):
    order = orderbook[name]

    if order["traded"] != "yes":
        return None

    if order["buy_sell"] != "BUY":
        return None

    sl_hit = tsl.get_order_status(orderid=order["sl_orderid"]) == "TRADED"
    tg_hit = ltp > order["tg"]

    if not (sl_hit or tg_hit):
        return None

    exit_type = None

    # ---- SL EXIT ----
    if sl_hit:
        order["exit_time"] = str(datetime.now().time())[:8]
        order["exit_price"] = tsl.get_executed_price(orderid=order["sl_orderid"])
        order["pnl"] = round(
            (order["exit_price"] - order["entry_price"]) * order["qty"], 1
        )
        order["remark"] = "Bought_SL_hit"
        exit_type = "SL"

    # ---- TG EXIT ----
    if tg_hit:
        # tsl.cancel_order(OrderID=order["sl_orderid"])
        # time.sleep(2)

        # square_off_id = tsl.order_placement(
        #     tradingsymbol=order["name"],
        #     exchange="NSE",
        #     quantity=order["qty"],
        #     price=0,
        #     trigger_price=0,
        #     order_type="MARKET",
        #     transaction_type="SELL",
        #     trade_type="MIS",
        # )
        square_off_id = "1234"

        order["exit_time"] = str(datetime.now().time())[:8]
        order["exit_price"] = tsl.get_executed_price(orderid=square_off_id)
        order["pnl"] = (order["exit_price"] - order["entry_price"]) * order["qty"]
        order["remark"] = "Bought_TG_hit"
        exit_type = "TG"

    completed_orders.append(order.copy())
    exited_order = order.copy()

    if reentry == "yes":
        orderbook[name] = get_empty_order()

    return {
        "exit_type": exit_type,
        "order": exited_order,
    }
