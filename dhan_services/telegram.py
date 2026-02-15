def send_alert_to_all(message, receiver_chat_ids, bot_token):
    """
    Sends a Telegram alert message to all receivers in the list.

    Args:
        message (str): Message text to send.
        receiver_chat_ids (list): List of chat IDs to send to.
        bot_token (str): Telegram bot token for authentication.
    """
    pass
    # for receiver in receiver_chat_ids:
    #     try:
    #         tsl.send_telegram_alert(
    #             message=message,
    #             receiver_chat_id=receiver,
    #             bot_token=bot_token,
    #         )
    #     except Exception as e:
    #         print(f"⚠️ Error sending message to {receiver}: {e}")
