import httpx

from app.models import User
from app.notifications.base import SEND_TIMEOUT_SECONDS, NotifyError, PageMessage


class SlackNotifier:
    channel = "slack"

    def __init__(self, bot_token: str, client: httpx.Client | None = None) -> None:
        self._token = bot_token
        self._client = client or httpx.Client(timeout=SEND_TIMEOUT_SECONDS)

    def address_for(self, user: User) -> str | None:
        return user.slack_user_id

    def send(self, address: str, message: PageMessage) -> None:
        try:
            response = self._client.post(
                "https://slack.com/api/chat.postMessage",
                headers={"Authorization": f"Bearer {self._token}"},
                json={"channel": address, "text": message.text},
            )
            response.raise_for_status()
            body = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise NotifyError(f"slack: {exc}") from exc
        # Slack reports most failures as HTTP 200 with ok=false.
        if not body.get("ok"):
            raise NotifyError(f"slack: {body.get('error', 'unknown error')}")
