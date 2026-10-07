from dataclasses import dataclass
from typing import Protocol

from app.models import User

SEND_TIMEOUT_SECONDS = 5.0


class NotifyError(Exception):
    pass


@dataclass(frozen=True)
class PageMessage:
    incident_id: int
    title: str
    severity: str
    level: int
    url: str

    @property
    def subject(self) -> str:
        return f"[{self.severity.upper()}] Incident #{self.incident_id}: {self.title}"

    @property
    def text(self) -> str:
        return f"{self.subject}\nEscalation level {self.level}. Acknowledge: {self.url}"


class Notifier(Protocol):
    channel: str

    def address_for(self, user: User) -> str | None:
        """Where to reach this user on this channel, or None if they have not set it up."""

    def send(self, address: str, message: PageMessage) -> None:
        """Deliver or raise NotifyError."""
