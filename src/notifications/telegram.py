import time
import requests
from tenacity import retry, stop_after_attempt, wait_exponential

TELEGRAM_API = "https://api.telegram.org"


def split_message(text: str, limit: int = 4000):
    if len(text) <= limit:
        return [text]
    parts = []
    cur = ""
    for line in text.splitlines(True):
        if len(cur) + len(line) > limit:
            parts.append(cur)
            cur = line
        else:
            cur += line
    if cur:
        parts.append(cur)
    return parts


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, max=10))
def send_telegram_message(bot_token: str, chat_id: str, text: str):
    """
    Sends text to Telegram, splitting if needed. Returns the last message's
    Telegram message_id (or None) so callers can log it in the alerts table.
    """
    if not text:
        raise ValueError("Empty telegram message")

    url = f"{TELEGRAM_API}/bot{bot_token}/sendMessage"
    last_message_id = None
    for part in split_message(text):
        resp = requests.post(
            url,
            json={"chat_id": chat_id, "text": part, "parse_mode": "Markdown"},
            timeout=30,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"Telegram send failed: {resp.status_code} {resp.text}")
        data = resp.json()
        last_message_id = (data.get("result") or {}).get("message_id")
        time.sleep(0.3)
    return last_message_id
