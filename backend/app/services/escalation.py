"""Escalation state machine.

State lives on the incident: `escalation_level` is the last level processed and
`next_escalation_at` is the deadline for moving on. The worker calls `tick` with the current
time; nothing in here reads the wall clock, which is what lets the tests drive it with a fake
one.

Paging only queues `Page` rows. Delivery happens separately (see `delivery.py`) so that a slow
or failing Slack call cannot hold up the escalation transaction.
"""

from collections.abc import Sequence
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import metrics
from app.models import EscalationLevel, Incident, IncidentStatus, Page, User
from app.notifications import Notifier
from app.services import schedules, timeline


def start(
    session: Session, incident: Incident, notifiers: Sequence[Notifier], now: datetime
) -> None:
    if incident.policy is None:
        timeline.record(
            incident, "escalation", "No escalation policy matched; nobody was paged.", now
        )
        return
    _advance(session, incident, notifiers, now)


def stop(incident: Incident) -> None:
    incident.next_escalation_at = None


def tick(session: Session, notifiers: Sequence[Notifier], now: datetime) -> int:
    """Escalate every open incident whose deadline has passed. Returns how many were handled."""
    due = session.scalars(
        select(Incident)
        .where(
            Incident.status == IncidentStatus.OPEN,
            Incident.next_escalation_at.is_not(None),
            Incident.next_escalation_at <= now,
        )
        .order_by(Incident.id)
        # Several worker replicas may poll at once; each incident is handled by whichever
        # locks it first and the others skip it.
        .with_for_update(skip_locked=True)
    ).all()
    for incident in due:
        _advance(session, incident, notifiers, now)
    return len(due)


def _advance(
    session: Session, incident: Incident, notifiers: Sequence[Notifier], now: datetime
) -> None:
    levels = incident.policy.levels if incident.policy else []
    remaining = [level for level in levels if level.position > incident.escalation_level]

    for level in remaining:
        incident.escalation_level = level.position
        pages = _pages_for(session, level, notifiers, now)
        if not pages:
            # An empty level must not eat its whole timeout while nobody knows about the
            # incident, so fall through to the next one straight away.
            timeline.record(
                incident,
                "escalation",
                f"Level {level.position} has nobody reachable; skipping.",
                now,
            )
            continue

        incident.pages.extend(pages)
        names = ", ".join(sorted({page.user.name for page in pages}))
        timeline.record(incident, "page", f"Paged level {level.position}: {names}.", now)
        metrics.ESCALATIONS.labels(level=str(level.position)).inc()

        is_last = level is levels[-1]
        incident.next_escalation_at = (
            None if is_last else now + timedelta(minutes=level.timeout_minutes)
        )
        return

    incident.next_escalation_at = None
    timeline.record(
        incident, "escalation", "Escalation policy exhausted without reaching anyone.", now
    )


def _pages_for(
    session: Session, level: EscalationLevel, notifiers: Sequence[Notifier], now: datetime
) -> list[Page]:
    pages = []
    for user in recipients(session, level, now):
        for notifier in notifiers:
            address = notifier.address_for(user)
            if address:
                pages.append(
                    Page(
                        level=level.position,
                        user=user,
                        channel=notifier.channel,
                        address=address,
                        created_at=now,
                    )
                )
    return pages


def recipients(session: Session, level: EscalationLevel, now: datetime) -> list[User]:
    """Users to page for a level, without duplicates, in target order."""
    found: dict[int, User] = {}
    for target in level.targets:
        if target.user is not None:
            found.setdefault(target.user.id, target.user)
        elif target.schedule is not None:
            current = schedules.on_call_at(target.schedule, now)
            if current is not None:
                found.setdefault(current.user_id, session.get_one(User, current.user_id))
    return list(found.values())
