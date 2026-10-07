from datetime import datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models import Incident, IncidentStatus, Page, ScheduleOverride
from app.services import alerts, delivery, escalation, incidents
from tests.conftest import (
    T0,
    RecordingNotifier,
    alert,
    make_policy,
    make_schedule,
    make_user,
    webhook,
)

PUBLIC_URL = "https://incidents.test"


@pytest.fixture
def people(session):
    return {name: make_user(session, name) for name in ("Alice", "Bob", "Carol")}


@pytest.fixture
def three_level_policy(session, people):
    """Level 1: Alice for 5 min, level 2: Bob for 10 min, level 3: Carol."""
    return make_policy(
        session, [(5, [people["Alice"]]), (10, [people["Bob"]]), (15, [people["Carol"]])]
    )


@pytest.fixture
def open_incident(session, clock, notifier):
    def run(**labels: str) -> Incident:
        payload = alerts.AlertmanagerWebhook.model_validate(webhook(alert(**labels)))
        alerts.ingest(session, payload, ["alertname", "service"], [notifier], clock.now())
        session.commit()
        return session.scalars(select(Incident).order_by(Incident.id.desc())).first()

    return run


@pytest.fixture
def tick(session, clock, notifier):
    """One worker pass at the fake clock's current time: escalate, then deliver."""

    def run() -> int:
        escalated = escalation.tick(session, [notifier], clock.now())
        session.commit()
        delivery.deliver_pending(session, [notifier], clock.now(), PUBLIC_URL)
        return escalated

    return run


def paged(incident: Incident) -> list[tuple[int, str]]:
    return [(page.level, page.user.name) for page in incident.pages]


class TestTiming:
    def test_level_one_is_paged_as_soon_as_the_incident_opens(
        self, three_level_policy, open_incident
    ):
        incident = open_incident()

        assert paged(incident) == [(1, "Alice")]
        assert incident.escalation_level == 1
        assert incident.next_escalation_at == T0 + timedelta(minutes=5)

    def test_nothing_happens_before_the_timeout(
        self, three_level_policy, open_incident, clock, tick
    ):
        incident = open_incident()
        clock.advance(minutes=4, seconds=59)

        assert tick() == 0
        assert paged(incident) == [(1, "Alice")]

    def test_next_level_is_paged_when_the_timeout_expires(
        self, three_level_policy, open_incident, clock, tick
    ):
        incident = open_incident()
        clock.advance(minutes=5)

        assert tick() == 1
        assert paged(incident) == [(1, "Alice"), (2, "Bob")]
        assert incident.next_escalation_at == clock.now() + timedelta(minutes=10)

    def test_walks_through_every_level_and_then_stops(
        self, three_level_policy, open_incident, clock, tick
    ):
        incident = open_incident()
        clock.advance(minutes=5)
        tick()
        clock.advance(minutes=10)
        tick()

        assert paged(incident) == [(1, "Alice"), (2, "Bob"), (3, "Carol")]
        assert incident.next_escalation_at is None

        clock.advance(hours=24)
        assert tick() == 0
        assert len(incident.pages) == 3

    def test_each_level_gets_its_full_timeout_even_if_the_worker_was_late(
        self, three_level_policy, open_incident, clock, tick
    ):
        incident = open_incident()
        clock.advance(minutes=8)  # worker was down for three minutes past the deadline
        tick()

        assert incident.next_escalation_at == T0 + timedelta(minutes=18)
        clock.advance(minutes=9, seconds=59)
        assert tick() == 0
        clock.advance(seconds=1)
        assert tick() == 1
        assert paged(incident)[-1] == (3, "Carol")

    def test_a_late_worker_escalates_one_level_per_pass_not_all_at_once(
        self, three_level_policy, open_incident, clock, tick
    ):
        incident = open_incident()
        clock.advance(hours=3)
        tick()

        assert paged(incident) == [(1, "Alice"), (2, "Bob")]

    def test_incidents_escalate_independently(self, three_level_policy, open_incident, clock, tick):
        first = open_incident(service="checkout")
        clock.advance(minutes=3)
        second = open_incident(service="search")

        clock.advance(minutes=2)
        assert tick() == 1
        assert first.escalation_level == 2
        assert second.escalation_level == 1

        clock.advance(minutes=3)
        assert tick() == 1
        assert second.escalation_level == 2


class TestStopping:
    def test_acknowledging_stops_escalation(
        self, session, people, three_level_policy, open_incident, clock, tick
    ):
        incident = open_incident()
        clock.advance(minutes=3)
        incidents.acknowledge(incident, people["Alice"], clock.now())
        session.commit()

        for _ in range(5):
            clock.advance(minutes=30)
            assert tick() == 0
        assert paged(incident) == [(1, "Alice")]
        assert incident.next_escalation_at is None

    def test_acknowledging_at_level_two_prevents_level_three(
        self, session, people, three_level_policy, open_incident, clock, tick
    ):
        incident = open_incident()
        clock.advance(minutes=5)
        tick()
        incidents.acknowledge(incident, people["Bob"], clock.now())
        session.commit()

        clock.advance(hours=1)
        tick()
        assert paged(incident) == [(1, "Alice"), (2, "Bob")]

    def test_manual_resolve_stops_escalation(
        self, session, people, three_level_policy, open_incident, clock, tick
    ):
        incident = open_incident()
        incidents.resolve(incident, people["Alice"], clock.now())
        session.commit()

        clock.advance(hours=1)
        assert tick() == 0
        assert paged(incident) == [(1, "Alice")]

    def test_alerts_resolving_stops_escalation(
        self, session, three_level_policy, open_incident, clock, tick, notifier
    ):
        incident = open_incident()
        payload = alerts.AlertmanagerWebhook.model_validate(webhook(alert(status="resolved")))
        alerts.ingest(session, payload, ["alertname", "service"], [notifier], clock.now())
        session.commit()

        clock.advance(hours=1)
        assert tick() == 0
        assert incident.status == IncidentStatus.RESOLVED
        assert paged(incident) == [(1, "Alice")]

    def test_acknowledging_a_resolved_incident_is_rejected(
        self, session, people, three_level_policy, open_incident, clock
    ):
        incident = open_incident()
        incidents.resolve(incident, people["Alice"], clock.now())

        with pytest.raises(incidents.InvalidTransition):
            incidents.acknowledge(incident, people["Bob"], clock.now())


class TestNoDoublePaging:
    def test_repeated_ticks_at_the_same_time_page_once(
        self, three_level_policy, open_incident, clock, tick, notifier
    ):
        incident = open_incident()
        tick()
        tick()
        clock.advance(minutes=5)
        for _ in range(10):
            tick()

        assert paged(incident) == [(1, "Alice"), (2, "Bob")]
        assert [address for address, _ in notifier.sent] == ["U-ALICE", "U-BOB"]

    def test_frequent_polling_over_the_whole_policy_sends_each_page_once(
        self, three_level_policy, open_incident, clock, tick, notifier
    ):
        incident = open_incident()
        for _ in range(60 * 12):  # one hour of 5-second polls
            tick()
            clock.advance(seconds=5)

        assert paged(incident) == [(1, "Alice"), (2, "Bob"), (3, "Carol")]
        assert [(address, message.level) for address, message in notifier.sent] == [
            ("U-ALICE", 1),
            ("U-BOB", 2),
            ("U-CAROL", 3),
        ]

    def test_user_targeted_twice_in_one_level_is_paged_once(self, session, people, open_incident):
        schedule = make_schedule(session, [people["Alice"]])
        make_policy(session, [(5, [schedule, people["Alice"], people["Bob"]])])

        assert paged(open_incident()) == [(1, "Alice"), (1, "Bob")]

    def test_database_rejects_a_duplicate_page(self, session, three_level_policy, open_incident):
        incident = open_incident()
        original = incident.pages[0]
        session.add(
            Page(
                incident_id=incident.id,
                level=original.level,
                user_id=original.user_id,
                channel=original.channel,
                address=original.address,
                created_at=T0,
            )
        )
        with pytest.raises(IntegrityError):
            session.flush()


class TestRecipients:
    def test_schedule_target_pages_whoever_is_on_call_at_that_moment(
        self, session, people, open_incident, clock, tick
    ):
        # Daily handoff at 12:03 UTC. The incident opens at 12:00 on Bob's shift and escalates
        # at 12:05, by which time Alice has taken over.
        schedule = make_schedule(
            session,
            [people["Bob"], people["Alice"]],
            rotation_start=datetime(2026, 3, 1, 12, 3),  # noqa: DTZ001
            shift_length_days=1,
        )
        make_policy(session, [(5, [schedule]), (5, [schedule])])

        incident = open_incident()
        clock.advance(minutes=5)
        tick()

        assert paged(incident) == [(1, "Bob"), (2, "Alice")]

    def test_override_holder_is_paged_instead_of_the_rotation(self, session, people, open_incident):
        schedule = make_schedule(session, [people["Alice"]])
        schedule.overrides.append(
            ScheduleOverride(
                user=people["Carol"],
                starts_at=T0 - timedelta(hours=1),
                ends_at=T0 + timedelta(hours=1),
            )
        )
        make_policy(session, [(5, [schedule])])

        assert paged(open_incident()) == [(1, "Carol")]

    def test_level_with_nobody_on_call_is_skipped_immediately(self, session, people, open_incident):
        not_started = make_schedule(
            session,
            [people["Alice"]],
            rotation_start=datetime(2030, 1, 1),  # noqa: DTZ001
        )
        make_policy(session, [(5, [not_started]), (10, [people["Bob"]]), (15, [people["Carol"]])])

        incident = open_incident()

        assert paged(incident) == [(2, "Bob")]
        assert incident.escalation_level == 2
        assert incident.next_escalation_at == T0 + timedelta(minutes=10)
        assert any("Level 1 has nobody reachable" in e.message for e in incident.timeline)

    def test_user_without_an_address_on_any_enabled_channel_is_skipped(
        self, session, people, open_incident
    ):
        people["Alice"].slack_user_id = None
        make_policy(session, [(5, [people["Alice"]]), (5, [people["Bob"]])])

        assert paged(open_incident()) == [(2, "Bob")]

    def test_policy_that_reaches_nobody_is_recorded_on_the_timeline(
        self, session, people, open_incident, clock, tick
    ):
        people["Alice"].slack_user_id = None
        make_policy(session, [(5, [people["Alice"]])])

        incident = open_incident()

        assert incident.pages == []
        assert incident.next_escalation_at is None
        assert "exhausted" in incident.timeline[-1].message
        clock.advance(hours=1)
        assert tick() == 0

    def test_user_is_paged_on_every_channel_they_have_configured(self, session, people, clock):
        people["Alice"].telegram_chat_id = "42"
        make_policy(session, [(5, [people["Alice"], people["Bob"]])])
        slack = RecordingNotifier("slack", "slack_user_id")
        telegram = RecordingNotifier("telegram", "telegram_chat_id")

        payload = alerts.AlertmanagerWebhook.model_validate(webhook(alert()))
        alerts.ingest(session, payload, ["alertname"], [slack, telegram], clock.now())
        session.commit()
        delivery.deliver_pending(session, [slack, telegram], clock.now(), PUBLIC_URL)

        assert [address for address, _ in slack.sent] == ["U-ALICE", "U-BOB"]
        assert [address for address, _ in telegram.sent] == ["42"]
