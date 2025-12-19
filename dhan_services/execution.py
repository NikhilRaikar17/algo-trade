from datetime import datetime
import time

from dhan_services.orderbook_template import get_empty_order
from dhan_login import PAPER_TRADING


def execute_buy_entry(tsl, name, cc, orderbook, current_time, paper_trading=True):
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
    order["direction"] = "LONG"
    order["qty"] = 1

    # ---- Entry order ----
    if paper_trading:
        # simulate order
        order["entry_orderid"] = "PAPER_ENTRY"
        order["entry_price"] = cc["close"]
    else:
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
    if paper_trading:
        order["sl_orderid"] = "PAPER_SL_1234"
    else:
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
    tsl, name, ltp, orderbook, completed_orders, reentry, paper_trading=True
):
    order = orderbook[name]

    # -------------------------------------------------
    # 1. GUARDS
    # -------------------------------------------------
    if order["traded"] != "yes":
        return None

    if order["direction"] not in ("LONG", "SHORT"):
        return None

    # -------------------------------------------------
    # 2. SL / TG DETECTION
    # -------------------------------------------------
    if paper_trading:
        if order["direction"] == "LONG":
            sl_hit = ltp < order["sl"]
            tg_hit = ltp > order["tg"]
        else:  # SHORT
            sl_hit = ltp > order["sl"]
            tg_hit = ltp < order["tg"]
    else:
        sl_hit = tsl.get_order_status(orderid=order["sl_orderid"]) == "TRADED"
        if order["direction"] == "LONG":
            tg_hit = ltp > order["tg"]
        else:
            tg_hit = ltp < order["tg"]

    if not (sl_hit or tg_hit):
        return None

    exit_type = "SL" if sl_hit else "TG"

    # -------------------------------------------------
    # 3. EXIT EXECUTION
    # -------------------------------------------------
    order["exit_time"] = str(datetime.now().time())[:8]

    if paper_trading:
        order["exit_price"] = ltp
    else:
        if exit_type == "SL":
            order["exit_price"] = tsl.get_executed_price(orderid=order["sl_orderid"])
        else:
            tsl.cancel_order(OrderID=order["sl_orderid"])
            time.sleep(2)

            square_off_id = tsl.order_placement(
                tradingsymbol=order["name"],
                exchange="NSE",
                quantity=order["qty"],
                price=0,
                trigger_price=0,
                order_type="MARKET",
                transaction_type=("SELL" if order["direction"] == "LONG" else "BUY"),
                trade_type="MIS",
            )
            order["exit_price"] = tsl.get_executed_price(orderid=square_off_id)

    # -------------------------------------------------
    # 4. PNL + REMARK
    # -------------------------------------------------
    if order["direction"] == "LONG":
        pnl = (order["exit_price"] - order["entry_price"]) * order["qty"]
        order["remark"] = "Bought_TG_hit" if exit_type == "TG" else "Bought_SL_hit"
    else:  # SHORT
        pnl = (order["entry_price"] - order["exit_price"]) * order["qty"]
        order["remark"] = "Short_TG_hit" if exit_type == "TG" else "Short_SL_hit"

    order["pnl"] = round(pnl, 1)

    # -------------------------------------------------
    # 5. FINALIZE
    # -------------------------------------------------
    completed_orders.append(order.copy())
    exited_order = order.copy()

    if reentry == "yes":
        orderbook[name] = get_empty_order()

    return {
        "exit_type": exit_type,
        "order": exited_order,
    }


def execute_sell_entry(
    tsl,
    name,
    cc,
    orderbook,
    current_time,
    paper_trading,
):
    order = orderbook[name]

    order["name"] = name
    order["date"] = str(current_time.date())
    order["entry_time"] = str(current_time.time())[:8]
    order["buy_sell"] = "SELL"
    order["direction"] = "SHORT"
    order["qty"] = 1

    # ---- ENTRY ----
    if paper_trading:
        order["entry_orderid"] = "PAPER_SELL_1234"
        order["entry_price"] = cc["close"]
    else:
        entry_orderid = tsl.order_placement(
            tradingsymbol=name,
            exchange="NSE",
            quantity=order["qty"],
            price=0,
            trigger_price=0,
            order_type="MARKET",
            transaction_type="SELL",
            trade_type="MIS",
        )
        order["entry_orderid"] = entry_orderid
        order["entry_price"] = tsl.get_executed_price(entry_orderid)

    # ---- SL / TG (INVERTED) ----
    order["sl"] = round(order["entry_price"] * 1.002, 1)  # SL ABOVE
    order["tg"] = round(order["entry_price"] * 0.998, 1)  # TG BELOW

    # ---- SL ORDER ----
    if paper_trading:
        order["sl_orderid"] = "PAPER_SL_1234"
    else:
        sl_orderid = tsl.order_placement(
            tradingsymbol=name,
            exchange="NSE",
            quantity=order["qty"],
            price=0,
            trigger_price=order["sl"],
            order_type="STOPMARKET",
            transaction_type="BUY",  # BUY to exit short
            trade_type="MIS",
        )
        order["sl_orderid"] = sl_orderid

    order["traded"] = "yes"
    return order
