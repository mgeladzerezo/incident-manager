from datetime import datetime
from typing import Any, Literal, Self
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    NaiveDatetime,
    field_validator,
    model_validator,
)

from app.auth import Role
from app.models import AlertStatus, IncidentStatus, PageStatus, PostmortemStatus


class OrmModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class UserOut(OrmModel):
    id: int
    email: str
    name: str
    slack_user_id: str | None
    telegram_chat_id: str | None


class UserCreate(BaseModel):
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+$", max_length=255)
    name: str = Field(min_length=1, max_length=255)
    slack_user_id: str | None = Field(default=None, max_length=64)
    telegram_chat_id: str | None = Field(default=None, max_length=64)


class UserUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    slack_user_id: str | None = Field(default=None, max_length=64)
    telegram_chat_id: str | None = Field(default=None, max_length=64)


class MeOut(BaseModel):
    user: UserOut
    roles: list[Role]


class AlertOut(OrmModel):
    id: int
    fingerprint: str
    status: AlertStatus
    labels: dict[str, str]
    annotations: dict[str, str]
    generator_url: str | None
    starts_at: datetime
    ends_at: datetime | None
    last_received_at: datetime


class TimelineEventOut(OrmModel):
    id: int
    kind: str
    message: str
    actor_name: str | None
    created_at: datetime


class PageOut(OrmModel):
    id: int
    level: int
    user_name: str
    channel: str
    status: PageStatus
    attempts: int
    last_error: str | None
    created_at: datetime
    sent_at: datetime | None


class IncidentSummary(OrmModel):
    id: int
    title: str
    severity: str
    status: IncidentStatus
    group_labels: dict[str, str]
    escalation_level: int
    alert_count: int
    firing_alert_count: int
    created_at: datetime
    acknowledged_at: datetime | None
    acknowledged_by_name: str | None
    resolved_at: datetime | None
    resolved_by_name: str | None


class IncidentDetail(IncidentSummary):
    policy_name: str | None
    next_escalation_at: datetime | None
    alerts: list[AlertOut]
    timeline: list[TimelineEventOut]
    pages: list[PageOut]


class NoteIn(BaseModel):
    text: str = Field(min_length=1, max_length=5000)


class PostmortemIn(BaseModel):
    content: dict[str, Any]
    status: PostmortemStatus = PostmortemStatus.DRAFT


class PostmortemOut(OrmModel):
    incident_id: int
    content: dict[str, Any]
    status: PostmortemStatus
    updated_at: datetime
    updated_by_name: str | None


class ScheduleIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    timezone: str
    # Local wall-clock time of the first handoff in `timezone`, without an offset.
    rotation_start: NaiveDatetime
    shift_length_days: int = Field(ge=1, le=365)
    participant_ids: list[int] = Field(min_length=1)

    @field_validator("timezone")
    @classmethod
    def timezone_exists(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"unknown time zone: {value}") from exc
        return value


class OverrideIn(BaseModel):
    user_id: int
    starts_at: AwareDatetime
    ends_at: AwareDatetime

    @model_validator(mode="after")
    def ends_after_start(self) -> Self:
        if self.ends_at <= self.starts_at:
            raise ValueError("ends_at must be after starts_at")
        return self


class OverrideOut(OrmModel):
    id: int
    user: UserOut
    starts_at: datetime
    ends_at: datetime


class ScheduleOut(OrmModel):
    id: int
    name: str
    timezone: str
    rotation_start: datetime
    shift_length_days: int
    users: list[UserOut]
    overrides: list[OverrideOut]


class ShiftOut(BaseModel):
    user: UserOut
    source: Literal["rotation", "override"]
    starts_at: datetime
    ends_at: datetime


class OnCallOut(BaseModel):
    user: UserOut | None
    source: Literal["rotation", "override"] | None


class TargetIn(BaseModel):
    schedule_id: int | None = None
    user_id: int | None = None

    @model_validator(mode="after")
    def exactly_one(self) -> Self:
        if (self.schedule_id is None) == (self.user_id is None):
            raise ValueError("a target needs exactly one of schedule_id and user_id")
        return self


class LevelIn(BaseModel):
    timeout_minutes: int = Field(ge=1, le=1440)
    targets: list[TargetIn] = Field(min_length=1)


class PolicyIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    is_default: bool = False
    # Level 1 first. Position is the index in this list.
    levels: list[LevelIn] = Field(min_length=1)


class TargetOut(OrmModel):
    schedule_id: int | None
    schedule_name: str | None
    user_id: int | None
    user_name: str | None


class LevelOut(OrmModel):
    position: int
    timeout_minutes: int
    targets: list[TargetOut]


class PolicyOut(OrmModel):
    id: int
    name: str
    is_default: bool
    levels: list[LevelOut]


class IngestOut(BaseModel):
    incidents_opened: int
    incidents_resolved: int
    alerts_added: int
    alerts_deduplicated: int
    alerts_resolved: int
    alerts_ignored: int
