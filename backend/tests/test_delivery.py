import pytest
from sqlalchemy import select

from app import worker
from app.models import Incident, PageStatus
from app.services import alerts, delivery, incidents
from tests.conftest import alert, make_policy, make_user, webhook

PUBLIC_URL = "https://incidents.test/"


@pytest.fixture
def incident(session, clock, notifier) -> Incident:
    make_policy(session, [(5, [make_user(session, "Alice")]), (5, [make_user(session, "Bob")])])
    payload = alerts.AlertmanagerWebhook.model_validate(webhook(alert()))
    alerts.ingest(session, payload, ["alertname"], [notifier], clock.now())
    session.commit()
    return session.scalars(select(Incident)).one()


def deliver(session, clock, notifier) -> int:
    return delivery.deliver_pending(session, [notifier], clock.now(), PUBLIC_URL)


def test_pending_page_is_sent_and_marked(session, clock, notifier, incident):
    assert deliver(session, clock, notifier) == 1

    (page,) = incident.pages
    address, message = notifier.sent[0]
    assert address == "U-ALICE"
    assert message.url == f"https://incidents.test/incidents/{incident.id}"
    assert message.subject == f"[CRITICAL] Incident #{incident.id}: HighErrorRate on checkout"
    assert (page.status, page.attempts, page.sent_at) == (PageStatus.SENT, 1, clock.now())


def test_sent_page_is_not_sent_again(session, clock, notifier, incident):
    deliver(session, clock, notifier)

    assert deliver(session, clock, notifier) == 0
    assert len(notifier.sent) == 1


def test_failed_send_is_retried_on_the_next_pass(session, clock, notifier, incident):
    notifier.failing = True
    assert deliver(session, clock, notifier) == 0
    (page,) = incident.pages
    assert (page.status, page.attempts) == (PageStatus.PENDING, 1)
    assert "simulated outage" in page.last_error

    notifier.failing = False
    assert deliver(session, clock, notifier) == 1
    assert (page.status, page.attempts, page.last_error) == (PageStatus.SENT, 2, None)


def test_page_is_marked_failed_after_the_last_attempt(session, clock, notifier, incident):
    notifier.failing = True
    for _ in range(delivery.MAX_ATTEMPTS + 2):
        deliver(session, clock, notifier)

    (page,) = incident.pages
    assert (page.status, page.attempts) == (PageStatus.FAILED, delivery.MAX_ATTEMPTS)


def test_queued_page_is_cancelled_if_the_incident_was_acknowledged_first(
    session, clock, notifier, incident
):
    incidents.acknowledge(incident, incident.pages[0].user, clock.now())
    session.commit()

    assert deliver(session, clock, notifier) == 0
    assert notifier.sent == []
    assert incident.pages[0].status == PageStatus.CANCELLED


def test_page_for_a_channel_that_is_no_longer_configured_fails(session, clock, incident):
    assert delivery.deliver_pending(session, [], clock.now(), PUBLIC_URL) == 0

    assert incident.pages[0].status == PageStatus.FAILED
    assert "not configured" in incident.pages[0].last_error


def test_worker_pass_escalates_then_delivers(session, session_factory, clock, notifier, incident):
    # The in-memory test database is a single connection, so the fixture's session must not
    # hold a transaction open while the worker uses its own sessions.
    session.rollback()
    assert worker.run_once(session_factory, clock, [notifier], PUBLIC_URL) == (0, 1)

    clock.advance(minutes=5)
    assert worker.run_once(session_factory, clock, [notifier], PUBLIC_URL) == (1, 1)
    assert worker.run_once(session_factory, clock, [notifier], PUBLIC_URL) == (0, 0)
    assert [(address, message.level) for address, message in notifier.sent] == [
        ("U-ALICE", 1),
        ("U-BOB", 2),
    ]
