import talib


def apply_indicators(chart):
    chart["rsi"] = talib.RSI(chart["close"], timeperiod=14)

    upper, middle, lower = talib.BBANDS(
        chart["close"], timeperiod=20, nbdevup=2, nbdevdn=2
    )
    chart["upper"] = upper
    chart["middle"] = middle
    chart["lower"] = lower

    return chart


def should_buy(cc, order):
    # if order["traded"] is not None:
    #     return False
    bc1 = cc["rsi"] > 55
    bc2 = order["traded"] is None
    bc3 = cc["close"] < cc["lower"]

    return bc1 and bc2
