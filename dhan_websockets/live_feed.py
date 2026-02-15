import threading
import time
from dhanhq import marketfeed

class LiveMarketFeed:
    def __init__(self, client_id, access_token, watchlist):
        self.latest_ltp = {}
        self.watchlist = watchlist
        self.feed = marketfeed.DhanFeed(
            client_id,
            access_token,
            [
                (marketfeed.NSE, sec_id, marketfeed.Ticker)
                for sec_id in watchlist.values()
            ],
            version="v2",
        )

    def _run_feed(self):
        self.feed.run_forever()

    def _consume_ticks(self):
        while True:
            data = self.feed.get_data()
            if data and "security_id" in data:
                self.latest_ltp[str(data["security_id"])] = float(data["LTP"])

    def start(self):
        threading.Thread(target=self._run_feed, daemon=True).start()
        threading.Thread(target=self._consume_ticks, daemon=True).start()
