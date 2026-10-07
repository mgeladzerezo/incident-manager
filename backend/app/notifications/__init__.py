from app.config import Settings
from app.notifications.base import Notifier, NotifyError, PageMessage
from app.notifications.email import EmailNotifier
from app.notifications.slack import SlackNotifier
from app.notifications.telegram import TelegramNotifier

__all__ = ["Notifier", "NotifyError", "PageMessage", "build_notifiers"]


def build_notifiers(settings: Settings) -> list[Notifier]:
    """Only channels with credentials are enabled; pages are never queued for the rest."""
    notifiers: list[Notifier] = []
    if settings.slack_bot_token:
        notifiers.append(SlackNotifier(settings.slack_bot_token))
    if settings.telegram_bot_token:
        notifiers.append(TelegramNotifier(settings.telegram_bot_token))
    if settings.smtp_host:
        notifiers.append(
            EmailNotifier(
                host=settings.smtp_host,
                port=settings.smtp_port,
                sender=settings.smtp_from,
                username=settings.smtp_username,
                password=settings.smtp_password,
                starttls=settings.smtp_starttls,
            )
        )
    return notifiers
