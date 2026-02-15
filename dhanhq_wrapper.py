import time
from dhanhq import dhanhq
from dhanhq.marketfeed import DhanFeed

# Add your Dhan Client ID and Access Token
client_id = "1108906427"
access_token = "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzUxMiJ9.eyJpc3MiOiJkaGFuIiwicGFydG5lcklkIjoiIiwiZXhwIjoxNzY2MjE1NjkzLCJpYXQiOjE3NjYxMjkyOTMsInRva2VuQ29uc3VtZXJUeXBlIjoiU0VMRiIsIndlYmhvb2tVcmwiOiIiLCJkaGFuQ2xpZW50SWQiOiIxMTA4OTA2NDI3In0.E2zGTHkD11eAF-zjLqdcGNOQ9DxJtIvkGc_JzJ4lMOtIkBYYEjDZ0KIU_XmJCYEQzHLAAIrJ-TTFv1HjTvqX8A"

dhan = dhanhq(client_id, access_token)
INSTRUMENTS = [("NSE_EQ", "2885")]


# -------------------------
# CALLBACK FUNCTION
# -------------------------
def on_message(data):
    print("Received Tick:")
    print(data)
    print("-" * 50)


def on_error(error):
    print("Error:", error)


def on_close():
    print("Connection closed")


import asyncio


async def main():
    # dhan = dhanhq(client_id=CLIENT_ID, access_token=ACCESS_TOKEN)

    feed = DhanFeed(
        client_id=client_id, access_token=access_token, instruments=INSTRUMENTS
    )

    feed.on_message = on_message
    feed.on_error = on_error
    feed.on_close = on_close

    print("Connecting to Dhan Live Market Feed...")
    await feed.connect()

    # Keep running
    while True:
        await asyncio.sleep(1)


# -------------------------
# ENTRY POINT
# -------------------------
if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Stopped by user")
