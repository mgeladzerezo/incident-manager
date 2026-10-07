import httpx

from app.models import User
from app.notifications.base import SEND_TIMEOUT_SECONDS, NotifyError, PageMessage


class TelegramNotifier:
    channel = "telegram"

    def __init__(self, bot_token: str, client: httpx.Client | None = None) -> None:
        self._url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        self._client = client or httpx.Client(timeout=SEND_TIMEOUT_SECONDS)

    def address_for(self, user: User) -> str | None:
        return user.telegram_chat_id

    def send(self, address: str, message: PageMessage) -> None:
        try:
            response = self._client.post(self._url, json={"chat_id": address, "text": message.text})
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            # The request URL contains the bot token, so it must not end up in last_error.
            raise NotifyError(f"telegram: HTTP {exc.response.status_code}") from exc
        except httpx.HTTPError as exc:
            raise NotifyError(f"telegram: {type(exc).__name__}") from exc
