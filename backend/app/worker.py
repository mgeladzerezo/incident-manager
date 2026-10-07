"""Escalation and delivery worker.

A plain polling loop instead of Celery: the only job is "look for due incidents and pending
pages every few seconds", all state is in PostgreSQL, and not needing a broker means one less
thing that can be down while people are trying to get paged. Running several replicas is safe
because rows are claimed with SELECT ... FOR UPDATE SKIP LOCKED.

    python -m app.worker
"""

import logging
import signal
import threading
from collections.abc import Sequence

from prometheus_client import start_http_server
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app import metrics
from app.clock import Clock, SystemClock
from app.config import Settings, get_settings
from app.db import make_engine, make_session_factory
from app.models import Incident, IncidentStatus
from app.notifications import Notifier, build_notifiers
from app.services import delivery, escalation

log = logging.getLogger("incident_manager.worker")


def run_once(
    session_factory: sessionmaker[Session],
    clock: Clock,
    notifiers: Sequence[Notifier],
    public_url: str,
) -> tuple[int, int]:
    """One pass: escalate what is due, then send what is queued."""
    with session_factory() as session:
        escalated = escalation.tick(session, notifiers, clock.now())
        session.commit()
    with session_factory() as session:
        sent = delivery.deliver_pending(session, notifiers, clock.now(), public_url)
    with session_factory() as session:
        _update_gauges(session)
    metrics.WORKER_LAST_TICK.set(clock.now().timestamp())
    return escalated, sent


def _update_gauges(session: Session) -> None:
    counts = dict(
        session.execute(
            select(Incident.status, func.count())
            .where(Incident.status != IncidentStatus.RESOLVED)
            .group_by(Incident.status)
        ).all()
    )
    for status in (IncidentStatus.OPEN, IncidentStatus.ACKNOWLEDGED):
        metrics.UNRESOLVED_INCIDENTS.labels(status=status.value).set(counts.get(status, 0))


def run_forever(settings: Settings, stop: threading.Event) -> None:
    session_factory = make_session_factory(make_engine(settings.database_url))
    notifiers = build_notifiers(settings)
    clock = SystemClock()
    log.info("worker started, channels=%s", [n.channel for n in notifiers])
    while not stop.is_set():
        try:
            escalated, sent = run_once(session_factory, clock, notifiers, settings.public_url)
            if escalated or sent:
                log.info("escalated=%d pages_sent=%d", escalated, sent)
        except Exception:
            # Keep polling through database restarts and failovers.
            log.exception("worker pass failed")
        stop.wait(settings.worker_poll_seconds)
    log.info("worker stopped")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = get_settings()
    stop = threading.Event()
    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, lambda *_: stop.set())
    start_http_server(settings.worker_metrics_port)
    run_forever(settings, stop)


if __name__ == "__main__":
    main()
