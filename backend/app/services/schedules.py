from datetime import datetime

from app.models import Schedule
from app.services import oncall


def rotation_of(schedule: Schedule) -> oncall.Rotation:
    return oncall.Rotation(
        timezone=schedule.timezone,
        start=schedule.rotation_start,
        shift_days=schedule.shift_length_days,
        participants=[p.user_id for p in schedule.participants],
    )


def overrides_of(schedule: Schedule) -> list[oncall.Override]:
    return [oncall.Override(o.id, o.user_id, o.starts_at, o.ends_at) for o in schedule.overrides]


def on_call_at(schedule: Schedule, at: datetime) -> oncall.OnCall | None:
    return oncall.on_call_at(rotation_of(schedule), overrides_of(schedule), at)


def shifts_between(schedule: Schedule, start: datetime, end: datetime) -> list[oncall.Shift]:
    return oncall.shifts_between(rotation_of(schedule), overrides_of(schedule), start, end)
