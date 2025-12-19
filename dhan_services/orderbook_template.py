def init_orderbook(watchlist):
    template = {
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
    return {name: template.copy() for name in watchlist}
