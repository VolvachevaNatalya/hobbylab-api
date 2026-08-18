import os
import logging
from datetime import datetime

import requests

logger = logging.getLogger(__name__)


def send_support_request(
    request_id: int,
    user_name: str,
    user_email: str,
    subject: str,
    message: str,
    created_at: datetime,
) -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_SUPPORT_CHAT_ID")
    if not token or not chat_id:
        return

    text = (
        f"New Support Request #{request_id}\n\n"
        f"User: {user_name}\n"
        f"Email: {user_email}\n"
        f"Subject: {subject}\n"
        f"Message: {message}\n"
        f"Created: {created_at}"
    )

    try:
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text},
            timeout=5,
        )
    except Exception:
        logger.exception("Telegram delivery failed for support request #%s", request_id)
