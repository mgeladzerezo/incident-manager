import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models import Alert, AlertStatus, Incident, IncidentStatus
from app.services import alerts, incidents
from tests.conftest import T0, alert, make_policy, make_user, webhook

GROUPING = ["alertname", "service"]


@pytest.fixture
def ingest(session, clock, notifier):
    def run(*items: dict) -> alerts.IngestResult:
        payload = alerts.AlertmanagerWebhook.model_validate(webhook(*items))
        result = alerts.ingest(session, payload, GROUPING, [notifier], clock.now())
        session.commit()
        return result

    return run


def all_incidents(session) -> list[Incident]:
    return list(session.scalars(select(Incident).order_by(Incident.id)))


class TestGrouping:
    def test_first_firing_alert_opens_an_incident(self, session, ingest):
        result = ingest(alert())

        (incident,) = all_incidents(session)
        assert result.incidents_opened == 1
        assert incident.status == IncidentStatus.OPEN
        assert incident.title == "HighErrorRate on checkout"
        assert incident.severity == "critical"
        assert incident.group_labels == {"alertname": "HighErrorRate", "service": "checkout"}
        assert incident.created_at == T0
        assert [a.status for a in incident.alerts] == [AlertStatus.FIRING]

    def test_alerts_sharing_grouping_labels_join_the_same_incident(self, session, ingest):
        ingest(alert(instance="web-1"))
        result = ingest(alert(instance="web-2"), alert(instance="web-3"))

        (incident,) = all_incidents(session)
        assert result.incidents_opened == 0
        assert result.alerts_added == 2
        assert sorted(a.labels["instance"] for a in incident.alerts) == ["web-1", "web-2", "web-3"]

    def test_alerts_in_one_payload_are_grouped_together(self, session, ingest):
        result = ingest(alert(instance="web-1"), alert(instance="web-2"))

        assert result.incidents_opened == 1
        assert len(all_incidents(session)) == 1

    def test_different_grouping_label_values_open_separate_incidents(self, session, ingest):
        ingest(
            alert(service="checkout"),
            alert(service="search"),
            alert(alertname="DiskFull", service="checkout"),
        )

        assert len(all_incidents(session)) == 3

    def test_labels_outside_the_grouping_set_do_not_split_incidents(self, session, ingest):
        ingest(alert(instance="web-1", pod="a"), alert(instance="web-2", pod="b", region="eu"))

        assert len(all_incidents(session)) == 1

    def test_missing_grouping_label_groups_as_empty_value(self, session, ingest):
        without_service = alert()
        del without_service["labels"]["service"]
        ingest(without_service, alert(service="checkout"))

        first, second = all_incidents(session)
        assert first.group_labels == {"alertname": "HighErrorRate", "service": ""}
        assert second.group_labels["service"] == "checkout"

    def test_group_key_does_not_depend_on_label_order(self):
        key_a = alerts.group_key_of({"alertname": "X", "service": "y"})
        key_b = alerts.group_key_of({"service": "y", "alertname": "X"})
        assert key_a == key_b

    def test_only_one_unresolved_incident_per_group_is_allowed_by_the_database(self, session):
        def incident() -> Incident:
            return Incident(title="t", group_key="k", group_labels={}, severity="s", created_at=T0)

        session.add(incident())
        session.flush()
        session.add(incident())
        with pytest.raises(IntegrityError):
            session.flush()


class TestDeduplication:
    def test_repeated_firing_alert_is_not_added_twice(self, session, clock, ingest):
        ingest(alert())
        clock.advance(minutes=5)
        result = ingest(alert())

        (incident,) = all_incidents(session)
        assert result.alerts_deduplicated == 1
        assert result.alerts_added == 0
        assert len(incident.alerts) == 1
        assert incident.alerts[0].last_received_at == clock.now()

    def test_duplicate_alert_inside_one_payload_is_stored_once(self, session, ingest):
        result = ingest(alert(), alert())

        assert (result.alerts_added, result.alerts_deduplicated) == (1, 1)
        assert len(session.scalars(select(Alert)).all()) == 1

    def test_alertmanager_fingerprint_takes_precedence_over_labels(self, session, ingest):
        # Same fingerprint, cosmetically different label set: still the same alert.
        ingest(alert(fingerprint="abc123", pod="a"))
        result = ingest(alert(fingerprint="abc123", pod="b"))

        assert result.alerts_deduplicated == 1
        assert len(session.scalars(select(Alert)).all()) == 1

    def test_without_fingerprint_the_full_label_set_identifies_the_alert(self, session, ingest):
        ingest(alert(instance="web-1"))
        result = ingest(alert(instance="web-1"), alert(instance="web-2"))

        assert (result.alerts_deduplicated, result.alerts_added) == (1, 1)

    def test_repeated_alert_does_not_page_again(self, session, ingest):
        make_policy(session, [(5, [make_user(session, "Alice")])])
        ingest(alert())
        ingest(alert())
        ingest(alert(instance="web-2"))

        (incident,) = all_incidents(session)
        assert len(incident.pages) == 1


class TestResolution:
    def test_incident_stays_open_while_any_alert_is_firing(self, session, ingest):
        ingest(alert(instance="web-1"), alert(instance="web-2"))
        result = ingest(alert(status="resolved", instance="web-1"))

        (incident,) = all_incidents(session)
        assert result.alerts_resolved == 1
        assert result.incidents_resolved == 0
        assert incident.status == IncidentStatus.OPEN
        assert incident.firing_alert_count == 1

    def test_incident_resolves_when_the_last_alert_resolves(self, session, clock, ingest):
        ingest(alert(instance="web-1"), alert(instance="web-2"))
        ingest(alert(status="resolved", instance="web-1"))
        clock.advance(minutes=3)
        result = ingest(alert(status="resolved", instance="web-2"))

        (incident,) = all_incidents(session)
        assert result.incidents_resolved == 1
        assert incident.status == IncidentStatus.RESOLVED
        assert incident.resolved_at == clock.now()
        assert incident.resolved_by is None
        assert incident.next_escalation_at is None

    def test_all_alerts_resolving_in_one_payload_resolves_the_incident(self, session, ingest):
        ingest(alert(instance="web-1"), alert(instance="web-2"))
        ingest(
            alert(status="resolved", instance="web-1"), alert(status="resolved", instance="web-2")
        )

        assert all_incidents(session)[0].status == IncidentStatus.RESOLVED

    def test_acknowledged_incident_also_resolves_with_its_alerts(self, session, clock, ingest):
        ingest(alert())
        incident = all_incidents(session)[0]
        incidents.acknowledge(incident, make_user(session, "Alice"), clock.now())
        session.commit()

        ingest(alert(status="resolved"))

        assert incident.status == IncidentStatus.RESOLVED

    def test_duplicate_resolved_notification_is_ignored(self, session, ingest):
        ingest(alert(instance="web-1"), alert(instance="web-2"))
        ingest(alert(status="resolved", instance="web-1"))
        result = ingest(alert(status="resolved", instance="web-1"))

        assert result.alerts_ignored == 1
        assert all_incidents(session)[0].status == IncidentStatus.OPEN

    def test_resolved_alert_that_was_never_seen_is_ignored(self, session, ingest):
        result = ingest(alert(status="resolved"))

        assert result.alerts_ignored == 1
        assert all_incidents(session) == []

    def test_resolved_alert_from_another_group_does_not_close_the_incident(self, session, ingest):
        ingest(alert(service="checkout"))
        ingest(alert(status="resolved", service="search"))

        assert all_incidents(session)[0].status == IncidentStatus.OPEN

    def test_alert_that_fires_again_keeps_the_incident_open(self, session, ingest):
        ingest(alert(instance="web-1"), alert(instance="web-2"))
        ingest(alert(status="resolved", instance="web-1"))
        ingest(alert(instance="web-1"))
        ingest(alert(status="resolved", instance="web-2"))

        (incident,) = all_incidents(session)
        assert incident.status == IncidentStatus.OPEN
        assert incident.firing_alert_count == 1
        assert len(incident.alerts) == 2

    def test_alert_firing_after_resolution_opens_a_new_incident(self, session, ingest):
        ingest(alert())
        ingest(alert(status="resolved"))
        result = ingest(alert())

        first, second = all_incidents(session)
        assert result.incidents_opened == 1
        assert first.status == IncidentStatus.RESOLVED
        assert second.status == IncidentStatus.OPEN
        assert first.group_key == second.group_key

    def test_resolved_alert_records_its_end_time(self, session, ingest):
        ingest(alert())
        ingest(alert(status="resolved"))

        stored = session.scalars(select(Alert)).one()
        assert stored.ends_at.isoformat() == "2026-03-02T12:05:00+00:00"


class TestPolicyRouting:
    def test_default_policy_is_used_when_no_label_names_one(self, session, ingest):
        default = make_policy(session, [(5, [make_user(session, "Alice")])])
        ingest(alert())

        assert all_incidents(session)[0].policy_id == default.id

    def test_escalation_policy_label_selects_a_policy_by_name(self, session, ingest):
        alice, bob = make_user(session, "Alice"), make_user(session, "Bob")
        make_policy(session, [(5, [alice])])
        database = make_policy(session, [(5, [bob])], name="database", is_default=False)
        ingest(alert(escalation_policy="database"))

        (incident,) = all_incidents(session)
        assert incident.policy_id == database.id
        assert [page.user_id for page in incident.pages] == [bob.id]

    def test_unknown_policy_label_falls_back_to_the_default(self, session, ingest):
        default = make_policy(session, [(5, [make_user(session, "Alice")])])
        ingest(alert(escalation_policy="does-not-exist"))

        assert all_incidents(session)[0].policy_id == default.id

    def test_incident_without_any_policy_is_still_recorded(self, session, ingest):
        ingest(alert())

        (incident,) = all_incidents(session)
        assert incident.pages == []
        assert incident.next_escalation_at is None
        assert any("No escalation policy" in event.message for event in incident.timeline)
