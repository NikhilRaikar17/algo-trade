def get_empty_order():
    return {
        "name": None,
        "date": None,
        "entry_time": None,
        "entry_price": None,
        "buy_sell": None,
        "qty": None,
        "sl": None,
        "tg": None,
        "exit_time": None,
        "exit_price": None,
        "pnl": None,
        "remark": None,
        "traded": None,
    }


def init_orderbook(watchlist):
    return {name: get_empty_order() for name in watchlist}
