import json
import urllib.request


def send_telegram_message(message, chat_id, bot_token):
    """Send a single Telegram message via the Bot API."""
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = json.dumps({
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML",
    }).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


def send_alert_to_all(message, receiver_chat_ids, bot_token):
    """
    Sends a Telegram alert message to all receivers in the list.

    Args:
        message (str): Message text to send.
        receiver_chat_ids (list): List of chat IDs to send to.
        bot_token (str): Telegram bot token for authentication.
    """
    for receiver in receiver_chat_ids:
        try:
            send_telegram_message(message, receiver, bot_token)
        except Exception as e:
            print(f"Error sending message to {receiver}: {e}")
