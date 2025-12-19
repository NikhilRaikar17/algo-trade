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
