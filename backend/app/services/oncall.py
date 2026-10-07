"""Who is on call at a given instant.

Pure functions over plain values so the rules can be tested without a database.

A rotation hands off at a fixed wall-clock time in the schedule's time zone. Shift N starts at
`start + N * shift_days` computed on the local calendar and only then converted to UTC, so a
09:00 handoff stays at 09:00 local across daylight saving changes. Overrides are absolute
intervals `[starts_at, ends_at)` and beat the rotation; when overrides overlap, the one created
last wins.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

Source = Literal["rotation", "override"]


@dataclass(frozen=True)
class Rotation:
    timezone: str
    start: datetime
    shift_days: int
    participants: Sequence[int]


@dataclass(frozen=True)
class Override:
    id: int
    user_id: int
    starts_at: datetime
    ends_at: datetime


@dataclass(frozen=True)
class OnCall:
    user_id: int
    source: Source


@dataclass(frozen=True)
class Shift:
    user_id: int
    source: Source
    starts_at: datetime
    ends_at: datetime


def on_call_at(rotation: Rotation, overrides: Sequence[Override], at: datetime) -> OnCall | None:
    _require_aware(at)
    active = [o for o in overrides if o.starts_at <= at < o.ends_at]
    if active:
        return OnCall(max(active, key=lambda o: o.id).user_id, "override")

    index = _shift_index(rotation, at)
    if index is None:
        return None
    return OnCall(rotation.participants[index % len(rotation.participants)], "rotation")


def shifts_between(
    rotation: Rotation, overrides: Sequence[Override], start: datetime, end: datetime
) -> list[Shift]:
    """Contiguous on-call segments covering [start, end), for calendar display.

    The answer can only change at a rotation handoff or at the edge of an override, so it is
    enough to ask `on_call_at` once per stretch between two such points.
    """
    _require_aware(start)
    _require_aware(end)
    if end <= start:
        return []

    cuts = {start, end}
    cuts.update(b for b in _handoffs_between(rotation, start, end))
    for override in overrides:
        cuts.update(t for t in (override.starts_at, override.ends_at) if start < t < end)
    points = sorted(cuts)

    shifts: list[Shift] = []
    for seg_start, seg_end in zip(points, points[1:], strict=False):
        current = on_call_at(rotation, overrides, seg_start)
        if current is None:
            continue
        previous = shifts[-1] if shifts else None
        if (
            previous
            and previous.ends_at == seg_start
            and (previous.user_id, previous.source) == (current.user_id, current.source)
        ):
            shifts[-1] = Shift(previous.user_id, previous.source, previous.starts_at, seg_end)
        else:
            shifts.append(Shift(current.user_id, current.source, seg_start, seg_end))
    return shifts


def handoff_time(rotation: Rotation, index: int) -> datetime:
    local = rotation.start + timedelta(days=index * rotation.shift_days)
    return local.replace(tzinfo=ZoneInfo(rotation.timezone)).astimezone(UTC)


def _shift_index(rotation: Rotation, at: datetime) -> int | None:
    if not rotation.participants:
        return None
    local = at.astimezone(ZoneInfo(rotation.timezone)).replace(tzinfo=None)
    index = (local - rotation.start) // timedelta(days=rotation.shift_days)
    # The wall-clock estimate can be one shift off next to a DST change; settle it against
    # the real handoff instants.
    while handoff_time(rotation, index + 1) <= at:
        index += 1
    while handoff_time(rotation, index) > at:
        index -= 1
    return index if index >= 0 else None


def _handoffs_between(rotation: Rotation, start: datetime, end: datetime) -> list[datetime]:
    if not rotation.participants:
        return []
    index = max(_shift_index(rotation, start) or 0, 0)
    handoffs = []
    while (boundary := handoff_time(rotation, index)) < end:
        if boundary > start:
            handoffs.append(boundary)
        index += 1
    return handoffs


def _require_aware(value: datetime) -> None:
    if value.tzinfo is None:
        raise ValueError("on-call lookups need a timezone-aware datetime")
