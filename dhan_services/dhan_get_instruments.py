from dhan_services.dhan_login import tsl
import pdb
from dhan_services.dhan_login import bot_token
import talib 


watchlist = ['MOTHERSON', 'OFSS', 'MANAPPURAM', 'BSOFT', 
            'CHAMBLFERT', 'DIXON', 'NATIONALUM', 'DLF', 'IDEA', 'ADANIPORTS', 
            'SAIL', 'HINDCOPPER', 'INDIGO', 'RECLTD', 'PNB', 'HINDALCO', 'RBLBANK', 'GNFC', 
            'ALKEM', 'CONCOR', 'PFC', 'GODREJPROP', 'MARUTI', 'ADANIENT', 'ONGC', 'CANBK', 
            'OBEROIRLTY', 'BANDHANBNK', 'SBIN', 'HINDPETRO', 'CANFINHOME', 'TATAMOTORS', 'LALPATHLAB', 'MCX', 
            'TATACHEM', 'BHARTIARTL', 'INDIAMART', 'LUPIN', 'INDUSTOWER', 'VEDL', 'SHRIRAMFIN', 'POLYCAB', 
            'WIPRO', 'UBL', 'SRF', 'BHARATFORG', 'GRASIM', 'IEX', 'BATAINDIA', 'AARTIIND', 'TATASTEEL', 'UPL', 
            'HDFCBANK', 'LTF', 'TVSMOTOR', 'GMRINFRA', 'IOC', 'ABCAPITAL', 'ACC', 'IDFCFIRSTB', 'ABFRL', 'ZYDUSLIFE', 
            'GLENMARK', 'TATAPOWER', 'PEL', 'IDFC', 'LAURUSLABS', 'BANKBARODA', 'KOTAKBANK', 'CUB', 'GAIL', 'DABUR', 
            'TECHM', 'CHOLAFIN', 'BEL', 'SYNGENE', 'FEDERALBNK', 'NAVINFLUOR', 'AXISBANK', 'LT', 'ICICIGI', 'EXIDEIND', 
            'TATACOMM', 'RELIANCE', 'ICICIPRULI', 'IPCALAB', 'AUBANK', 'INDIACEM', 'GRANULES', 'HDFCAMC', 'COFORGE', 
            'LICHSGFIN', 'BAJAJFINSV', 'INFY', 'BRITANNIA', 'M&MFIN', 'BAJFINANCE', 'PIIND', 'DEEPAKNTR', 'SHREECEM', 
            'INDUSINDBK', 'DRREDDY', 'TCS', 'BPCL', 'PETRONET', 'NAUKRI', 'JSWSTEEL', 'MUTHOOTFIN', 'CUMMINSIND', 'CROMPTON', 'M&M', 'GODREJCP', 'IGL', 'BAJAJ-AUTO', 'HEROMOTOCO', 'AMBUJACEM', 'BIOCON', 'ULTRACEMCO', 'VOLTAS', 
            'BALRAMCHIN', 'SUNPHARMA', 'ASIANPAINT', 'COALINDIA', 'SUNTV', 'EICHERMOT', 'ESCORTS', 'HAL', 'ASTRAL', 'NMDC', 
            'ICICIBANK', 'TORNTPHARM', 'JUBLFOOD', 'METROPOLIS', 'RAMCOCEM', 'INDHOTEL', 'HINDUNILVR', 'TRENT', 'TITAN', 'JKCEMENT', 
            'ASHOKLEY', 'SBICARD', 'BERGEPAINT', 'JINDALSTEL', 'MFSL', 'BHEL', 'NESTLEIND', 'HDFCLIFE', 'COROMANDEL', 'DIVISLAB', 
            'ITC', 'TATACONSUM', 'APOLLOTYRE', 'AUROPHARMA', 'HCLTECH', 'LTTS', 'BALKRISIND', 'DALBHARAT', 'APOLLOHOSP', 
            'ABBOTINDIA', 'ATUL', 'UNITDSPR', 'PVRINOX', 'SIEMENS', 'SBILIFE', 'IRCTC', 'GUJGASLTD', 'BOSCHLTD', 'NTPC', 
            'POWERGRID', 'MARICO', 'HAVELLS', 'MPHASIS', 'COLPAL', 'CIPLA', 'MGL', 'ABB', 'PIDILITIND', 'MRF', 'LTIM', 
            'PAGEIND', 'PERSISTENT']
watchlist = ["ADANIPORTS", "SBIN", "CIPLA", "RELIANCE"]
reciever_chat_id = ["8272803637", "1623717769"]
available_balance = tsl.get_balance()

for name in watchlist:
    try:
        print(f"Getting data for {name}")
        charts = tsl.get_historical_data(tradingsymbol=name, exchange="NSE", timeframe="5")
        closing_price = charts['close'].iloc[-1]
        charts['rsi'] = talib.RSI(charts['close'], timeperiod=14)
        cc = charts.iloc[-2]
        uptrend = cc['rsi'] > 50
        downtrend = cc['rsi'] < 49
        rsi_value = round(cc['rsi'], 2)

        charts['sma20'] = talib.SMA(charts['close'], timeperiod=20)
        charts['sma50'] = talib.SMA(charts['close'], timeperiod=50)
        latest = charts.iloc[-1]
        prev = charts.iloc[-2]

        if latest['sma20'] > latest['sma50']:
            trend = "Uptrend"
            trend_emoji = "🔺"
        elif latest['sma20'] < latest['sma50']:
            trend = "Downtrend"
            trend_emoji = "🔻"
        else:
            trend = "Sideways"
            trend_emoji = "⚪️"

        if uptrend:
            print(name, "is in uptrend, Buy this script")
            signal = "BUY"
            sl_price = round((cc['close']*0.98),1)

        if downtrend:
            print(name, "is in downtrend, Sell this script")
            signal = "SELL"
            sl_price = round((cc['close']*1.02),1)

        message = (
                    f"Stock: {name}\n"
                    f"Closing Price: {closing_price}\n"
                    f"RSI: {rsi_value}\n"
                    f"Trend: {trend}{trend_emoji}\n"
                    f"Signal:{signal}\n"
                    f"StopLoss:{sl_price}\n"
                    f"Available Balance:{available_balance} \n"
                )
        for rec in reciever_chat_id:
            tsl.send_telegram_alert(message=message, receiver_chat_id=rec, bot_token=bot_token)
    except Exception as e:
        print(f"Something wrong with stock : {name}, Exception:", e)
        continue 