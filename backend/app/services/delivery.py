"""Sends queued pages.

Each page is handled in its own transaction while holding a row lock, so two workers never
send the same page. Delivery is at-least-once: if the process dies between a successful send
and the commit, the page is still pending and will be sent again.
"""

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import metrics
from app.models import IncidentStatus, Page, PageStatus
from app.notifications import Notifier, NotifyError, PageMessage

MAX_ATTEMPTS = 3


def deliver_pending(
    session: Session, notifiers: Sequence[Notifier], now: datetime, public_url: str
) -> int:
    """Try every pending page once. Returns the number of pages sent."""
    by_channel = {notifier.channel: notifier for notifier in notifiers}
    sent = 0
    last_id = 0
    while (page := _next_pending(session, last_id)) is not None:
        last_id = page.id
        if _deliver(page, by_channel.get(page.channel), now, public_url):
            sent += 1
        session.commit()
    return sent


def _next_pending(session: Session, after_id: int) -> Page | None:
    return session.scalars(
        select(Page)
        .where(Page.status == PageStatus.PENDING, Page.id > after_id)
        .order_by(Page.id)
        .limit(1)
        .with_for_update(skip_locked=True)
    ).first()


def _deliver(page: Page, notifier: Notifier | None, now: datetime, public_url: str) -> bool:
    incident = page.incident
    if incident.status != IncidentStatus.OPEN:
        # Acknowledged or resolved while the page was still queued.
        page.status = PageStatus.CANCELLED
        return False
    if notifier is None:
        page.status = PageStatus.FAILED
        page.last_error = f"channel {page.channel} is not configured"
        return False

    message = PageMessage(
        incident_id=incident.id,
        title=incident.title,
        severity=incident.severity,
        level=page.level,
        url=f"{public_url.rstrip('/')}/incidents/{incident.id}",
    )
    page.attempts += 1
    try:
        notifier.send(page.address, message)
    except NotifyError as exc:
        page.last_error = str(exc)
        if page.attempts >= MAX_ATTEMPTS:
            page.status = PageStatus.FAILED
        metrics.PAGES.labels(channel=page.channel, result="error").inc()
        return False

    page.status = PageStatus.SENT
    page.sent_at = now
    page.last_error = None
    metrics.PAGES.labels(channel=page.channel, result="sent").inc()
    return True
