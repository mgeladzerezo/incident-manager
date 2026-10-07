import smtplib
from collections.abc import Callable
from email.message import EmailMessage

from app.models import User
from app.notifications.base import SEND_TIMEOUT_SECONDS, NotifyError, PageMessage


class EmailNotifier:
    channel = "email"

    def __init__(
        self,
        host: str,
        port: int,
        sender: str,
        username: str = "",
        password: str = "",
        starttls: bool = True,
        smtp_factory: Callable[..., smtplib.SMTP] = smtplib.SMTP,
    ) -> None:
        self._host = host
        self._port = port
        self._sender = sender
        self._username = username
        self._password = password
        self._starttls = starttls
        self._smtp_factory = smtp_factory

    def address_for(self, user: User) -> str | None:
        return user.email

    def send(self, address: str, message: PageMessage) -> None:
        email = EmailMessage()
        email["From"] = self._sender
        email["To"] = address
        email["Subject"] = message.subject
        email.set_content(message.text)
        try:
            with self._smtp_factory(self._host, self._port, timeout=SEND_TIMEOUT_SECONDS) as smtp:
                if self._starttls:
                    smtp.starttls()
                if self._username:
                    smtp.login(self._username, self._password)
                smtp.send_message(email)
        except (smtplib.SMTPException, OSError) as exc:
            raise NotifyError(f"email: {exc}") from exc
