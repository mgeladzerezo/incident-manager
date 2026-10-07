import json
import smtplib

import httpx
import pytest

from app.config import Settings
from app.notifications import NotifyError, PageMessage, build_notifiers
from app.notifications.email import EmailNotifier
from app.notifications.slack import SlackNotifier
from app.notifications.telegram import TelegramNotifier

MESSAGE = PageMessage(
    incident_id=7,
    title="Disk full",
    severity="critical",
    level=2,
    url="https://incidents.test/incidents/7",
)


def client_returning(response: httpx.Response, seen: list[httpx.Request]) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return response

    return httpx.Client(transport=httpx.MockTransport(handler))


class TestSlack:
    def test_posts_a_direct_message_with_the_bot_token(self):
        seen: list[httpx.Request] = []
        client = client_returning(httpx.Response(200, json={"ok": True}), seen)

        SlackNotifier("xoxb-secret", client).send("U123", MESSAGE)

        (request,) = seen
        assert str(request.url) == "https://slack.com/api/chat.postMessage"
        assert request.headers["Authorization"] == "Bearer xoxb-secret"
        body = json.loads(request.content)
        assert body["channel"] == "U123"
        assert "Incident #7: Disk full" in body["text"]
        assert "https://incidents.test/incidents/7" in body["text"]

    def test_ok_false_with_http_200_is_an_error(self):
        client = client_returning(
            httpx.Response(200, json={"ok": False, "error": "channel_not_found"}), []
        )

        with pytest.raises(NotifyError, match="channel_not_found"):
            SlackNotifier("token", client).send("U123", MESSAGE)

    def test_http_error_is_an_error(self):
        client = client_returning(httpx.Response(503), [])

        with pytest.raises(NotifyError):
            SlackNotifier("token", client).send("U123", MESSAGE)


class TestTelegram:
    def test_calls_send_message_for_the_chat(self):
        seen: list[httpx.Request] = []
        client = client_returning(httpx.Response(200, json={"ok": True}), seen)

        TelegramNotifier("123:abc", client).send("42", MESSAGE)

        (request,) = seen
        assert str(request.url) == "https://api.telegram.org/bot123:abc/sendMessage"
        assert json.loads(request.content)["chat_id"] == "42"

    def test_error_message_does_not_leak_the_bot_token(self):
        client = client_returning(httpx.Response(403), [])

        with pytest.raises(NotifyError) as error:
            TelegramNotifier("123:abc", client).send("42", MESSAGE)
        assert "123:abc" not in str(error.value)
        assert "403" in str(error.value)


class FakeSmtp:
    instances: list["FakeSmtp"] = []

    def __init__(self, host: str, port: int, timeout: float) -> None:
        self.address = (host, port)
        self.calls: list[str] = []
        self.messages = []
        FakeSmtp.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self):
        self.calls.append("starttls")

    def login(self, username, password):
        self.calls.append(f"login:{username}")

    def send_message(self, message):
        self.calls.append("send")
        self.messages.append(message)


class RefusingSmtp(FakeSmtp):
    def send_message(self, message):
        raise smtplib.SMTPRecipientsRefused({})


class TestEmail:
    def setup_method(self):
        FakeSmtp.instances.clear()

    def test_sends_over_starttls_with_login(self):
        notifier = EmailNotifier(
            "smtp.test", 587, "incidents@test", "user", "secret", smtp_factory=FakeSmtp
        )

        notifier.send("alice@example.com", MESSAGE)

        (smtp,) = FakeSmtp.instances
        assert smtp.address == ("smtp.test", 587)
        assert smtp.calls == ["starttls", "login:user", "send"]
        (email,) = smtp.messages
        assert email["To"] == "alice@example.com"
        assert email["From"] == "incidents@test"
        assert email["Subject"] == "[CRITICAL] Incident #7: Disk full"

    def test_skips_starttls_and_login_when_not_configured(self):
        notifier = EmailNotifier(
            "smtp.test", 25, "incidents@test", starttls=False, smtp_factory=FakeSmtp
        )

        notifier.send("alice@example.com", MESSAGE)

        assert FakeSmtp.instances[0].calls == ["send"]

    def test_smtp_failure_is_an_error(self):
        notifier = EmailNotifier("smtp.test", 587, "incidents@test", smtp_factory=RefusingSmtp)

        with pytest.raises(NotifyError):
            notifier.send("alice@example.com", MESSAGE)


def test_only_channels_with_credentials_are_enabled():
    def channels(**overrides) -> list[str]:
        return [n.channel for n in build_notifiers(Settings(_env_file=None, **overrides))]

    assert channels() == []
    assert channels(slack_bot_token="x") == ["slack"]
    assert channels(telegram_bot_token="x", smtp_host="smtp.test") == ["telegram", "email"]
