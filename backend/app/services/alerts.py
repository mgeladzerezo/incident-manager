"""Turns Alertmanager webhook payloads into incidents.

Two keys drive everything:

* the alert fingerprint identifies one alert (one label set). A repeated delivery of the same
  firing alert only refreshes it;
* the group key is a hash of the configured grouping labels. All alerts with the same group key
  land in the same unresolved incident.

An incident resolves on its own only once every alert in it has resolved.
"""

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from pydantic import AwareDatetime, BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import metrics
from app.models import Alert, AlertStatus, EscalationPolicy, Incident, IncidentStatus
from app.notifications import Notifier
from app.services import escalation, timeline

POLICY_LABEL = "escalation_policy"


class AlertmanagerAlert(BaseModel):
    status: AlertStatus
    labels: dict[str, str]
    annotations: dict[str, str] = Field(default_factory=dict)
    starts_at: AwareDatetime = Field(alias="startsAt")
    ends_at: AwareDatetime | None = Field(default=None, alias="endsAt")
    generator_url: str | None = Field(default=None, alias="generatorURL")
    fingerprint: str = ""


class AlertmanagerWebhook(BaseModel):
    alerts: list[AlertmanagerAlert]


@dataclass
class IngestResult:
    incidents_opened: int = 0
    incidents_resolved: int = 0
    alerts_added: int = 0
    alerts_deduplicated: int = 0
    alerts_resolved: int = 0
    alerts_ignored: int = 0


def fingerprint_of(alert: AlertmanagerAlert) -> str:
    # Alertmanager sends its own fingerprint since webhook version 4; hash the label set for
    # senders that do not.
    return alert.fingerprint or _digest(alert.labels)


def group_labels_of(alert: AlertmanagerAlert, grouping_labels: Sequence[str]) -> dict[str, str]:
    return {name: alert.labels.get(name, "") for name in grouping_labels}


def group_key_of(group_labels: dict[str, str]) -> str:
    return _digest(group_labels)


def ingest(
    session: Session,
    payload: AlertmanagerWebhook,
    grouping_labels: Sequence[str],
    notifiers: Sequence[Notifier],
    now: datetime,
) -> IngestResult:
    result = IngestResult()
    for alert in payload.alerts:
        if alert.status == AlertStatus.FIRING:
            _handle_firing(session, alert, grouping_labels, notifiers, now, result)
        else:
            _handle_resolved(session, alert, grouping_labels, now, result)

    metrics.ALERTS_RECEIVED.labels(outcome="added").inc(result.alerts_added)
    metrics.ALERTS_RECEIVED.labels(outcome="deduplicated").inc(result.alerts_deduplicated)
    metrics.ALERTS_RECEIVED.labels(outcome="resolved").inc(result.alerts_resolved)
    metrics.ALERTS_RECEIVED.labels(outcome="ignored").inc(result.alerts_ignored)
    return result


def _handle_firing(
    session: Session,
    alert: AlertmanagerAlert,
    grouping_labels: Sequence[str],
    notifiers: Sequence[Notifier],
    now: datetime,
    result: IngestResult,
) -> None:
    group_labels = group_labels_of(alert, grouping_labels)
    group_key = group_key_of(group_labels)

    incident = _active_incident(session, group_key)
    if incident is None:
        incident = _open_incident(session, alert, group_key, group_labels, now)
        if incident is not None:
            escalation.start(session, incident, notifiers, now)
            metrics.INCIDENTS_OPENED.labels(severity=incident.severity).inc()
            result.incidents_opened += 1
        else:
            # Lost the race against a concurrent delivery; join the incident it created.
            incident = _active_incident(session, group_key)
            if incident is None:
                result.alerts_ignored += 1
                return

    fingerprint = fingerprint_of(alert)
    existing = next((a for a in incident.alerts if a.fingerprint == fingerprint), None)
    if existing is None:
        incident.alerts.append(
            Alert(
                fingerprint=fingerprint,
                status=AlertStatus.FIRING,
                labels=alert.labels,
                annotations=alert.annotations,
                generator_url=alert.generator_url,
                starts_at=alert.starts_at,
                last_received_at=now,
            )
        )
        if len(incident.alerts) > 1:
            timeline.record(incident, "alert", f"Alert added: {_describe(alert)}.", now)
        result.alerts_added += 1
        return

    existing.last_received_at = now
    existing.annotations = alert.annotations
    if existing.status == AlertStatus.RESOLVED:
        existing.status = AlertStatus.FIRING
        existing.starts_at = alert.starts_at
        existing.ends_at = None
        timeline.record(incident, "alert", f"Alert firing again: {_describe(alert)}.", now)
        result.alerts_added += 1
    else:
        result.alerts_deduplicated += 1


def _handle_resolved(
    session: Session,
    alert: AlertmanagerAlert,
    grouping_labels: Sequence[str],
    now: datetime,
    result: IngestResult,
) -> None:
    group_key = group_key_of(group_labels_of(alert, grouping_labels))
    incident = _active_incident(session, group_key)
    fingerprint = fingerprint_of(alert)
    existing = (
        next((a for a in incident.alerts if a.fingerprint == fingerprint), None)
        if incident
        else None
    )
    if incident is None or existing is None or existing.status == AlertStatus.RESOLVED:
        # Nothing to close: never seen, already resolved, or the incident was closed by hand.
        result.alerts_ignored += 1
        return

    existing.status = AlertStatus.RESOLVED
    existing.ends_at = alert.ends_at or now
    existing.last_received_at = now
    result.alerts_resolved += 1

    still_firing = sum(1 for a in incident.alerts if a.status == AlertStatus.FIRING)
    if still_firing:
        timeline.record(
            incident,
            "alert",
            f"Alert resolved: {_describe(alert)}. {still_firing} still firing.",
            now,
        )
        return

    incident.status = IncidentStatus.RESOLVED
    incident.resolved_at = now
    escalation.stop(incident)
    timeline.record(incident, "resolved", "All alerts resolved; incident closed.", now)
    result.incidents_resolved += 1


def _active_incident(session: Session, group_key: str) -> Incident | None:
    return session.scalars(
        select(Incident)
        .where(Incident.group_key == group_key, Incident.status != IncidentStatus.RESOLVED)
        .with_for_update()
    ).first()


def _open_incident(
    session: Session,
    alert: AlertmanagerAlert,
    group_key: str,
    group_labels: dict[str, str],
    now: datetime,
) -> Incident | None:
    """Insert a new incident, or return None if another transaction opened one first."""
    incident = Incident(
        title=alert.annotations.get("summary") or alert.labels.get("alertname") or "Alert",
        group_key=group_key,
        group_labels=group_labels,
        severity=alert.labels.get("severity", "unknown"),
        status=IncidentStatus.OPEN,
        policy=_policy_for(session, alert),
        escalation_level=0,
        created_at=now,
    )
    try:
        # Savepoint, so hitting the unique index on active group keys does not throw away
        # the alerts already processed in this request.
        with session.begin_nested():
            session.add(incident)
            session.flush()
    except IntegrityError:
        return None
    timeline.record(incident, "opened", f"Incident opened by alert {_describe(alert)}.", now)
    return incident


def _policy_for(session: Session, alert: AlertmanagerAlert) -> EscalationPolicy | None:
    name = alert.labels.get(POLICY_LABEL)
    if name:
        policy = session.scalars(
            select(EscalationPolicy).where(EscalationPolicy.name == name)
        ).first()
        if policy is not None:
            return policy
    return session.scalars(
        select(EscalationPolicy).where(EscalationPolicy.is_default.is_(True))
    ).first()


def _describe(alert: AlertmanagerAlert) -> str:
    name = alert.labels.get("alertname", "alert")
    instance = alert.labels.get("instance")
    return f"{name} on {instance}" if instance else name


def _digest(values: dict[str, str]) -> str:
    canonical = json.dumps(values, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()
