from datetime import datetime

from app.models import Incident, TimelineEvent, User


def record(
    incident: Incident, kind: str, message: str, now: datetime, actor: User | None = None
) -> None:
    incident.timeline.append(TimelineEvent(kind=kind, message=message, created_at=now, actor=actor))
