watchlist = [
    "BEL",
    "BOSCHLTD",
    "COLPAL",
    "HCLTECH",
    "HDFCBANK",
    "HAVELLS",
    "HAL",
    "ITC",
    "IRCTC",
    "INFY",
    "LTIM",
    "MARICO",
    "MARUTI",
    "NESTLEIND",
    "PIDILITIND",
    "TCS",
    "TECHM",
    "WIPRO",
]


# pre_market_watchlist        = ['ASIANPAINT', 'BAJAJ-AUTO', 'BERGEPAINT', 'BEL', 'BOSCHLTD', 'BRITANNIA', 'COALINDIA', 'COLPAL', 'DABUR', 'DIVISLAB', 'EICHERMOT', 'GODREJCP', 'HCLTECH', 'HDFCBANK', 'HAVELLS', 'HEROMOTOCO', 'HAL', 'HINDUNILVR', 'ITC', 'IRCTC', 'INFY', 'LTIM', 'MARICO', 'MARUTI', 'NESTLEIND', 'PIDILITIND', 'TCS', 'TECHM', 'WIPRO']
# watchlist                   = []

# for name in pre_market_watchlist:

# 	print("Pre market scanning ", name)
# 	day_chart = tsl.get_historical_data(tradingsymbol = name,exchange = 'NSE',timeframe="DAY")
# 	day_chart['upperband'], day_chart['middleband'], day_chart['lowerband'] = talib.BBANDS(day_chart['close'], timeperiod=20, nbdevup=2, nbdevdn=2, matype=0)


# 	last_day_candle = day_chart.iloc[-1]

# 	upper_breakout = last_day_candle['high'] > last_day_candle['upperband']
# 	lower_breakout = last_day_candle['low'] < last_day_candle['lowerband']

# 	if upper_breakout or lower_breakout:
# 		watchlist.append(name)
# 		print(f"\t selected {name} for trading")
# 		pdb.set_trace()


# print(watchlist)
