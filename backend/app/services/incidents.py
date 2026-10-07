from datetime import datetime

from app.models import Incident, IncidentStatus, User
from app.services import escalation, timeline


class InvalidTransition(Exception):
    pass


def acknowledge(incident: Incident, user: User, now: datetime) -> None:
    if incident.status == IncidentStatus.ACKNOWLEDGED:
        return
    if incident.status != IncidentStatus.OPEN:
        raise InvalidTransition(f"cannot acknowledge a {incident.status} incident")
    incident.status = IncidentStatus.ACKNOWLEDGED
    incident.acknowledged_at = now
    incident.acknowledged_by = user
    escalation.stop(incident)
    timeline.record(incident, "acknowledged", f"Acknowledged by {user.name}.", now, actor=user)


def resolve(incident: Incident, user: User, now: datetime) -> None:
    if incident.status == IncidentStatus.RESOLVED:
        return
    incident.status = IncidentStatus.RESOLVED
    incident.resolved_at = now
    incident.resolved_by = user
    escalation.stop(incident)
    timeline.record(incident, "resolved", f"Resolved by {user.name}.", now, actor=user)


def add_note(incident: Incident, user: User, text: str, now: datetime) -> None:
    timeline.record(incident, "note", text, now, actor=user)
