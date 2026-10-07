from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, UTCDateTime


class IncidentStatus(StrEnum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"


class AlertStatus(StrEnum):
    FIRING = "firing"
    RESOLVED = "resolved"


class PageStatus(StrEnum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"
    CANCELLED = "cancelled"


class PostmortemStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    # OIDC subject. Null until the person logs in for the first time; admins can pre-create
    # users by email so they can be put on a schedule before that.
    subject: Mapped[str | None] = mapped_column(String(255), unique=True)
    email: Mapped[str] = mapped_column(String(255), unique=True)
    name: Mapped[str] = mapped_column(String(255))
    slack_user_id: Mapped[str | None] = mapped_column(String(64))
    telegram_chat_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)


class Schedule(Base):
    __tablename__ = "schedules"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True)
    timezone: Mapped[str] = mapped_column(String(64))
    # Wall-clock time in `timezone` of the first handoff. Kept naive on purpose: handoffs follow
    # the local clock ("Mondays 09:00"), so their UTC instant moves with daylight saving time.
    rotation_start: Mapped[datetime] = mapped_column(DateTime(timezone=False))
    shift_length_days: Mapped[int] = mapped_column(Integer)

    participants: Mapped[list["ScheduleParticipant"]] = relationship(
        back_populates="schedule",
        order_by="ScheduleParticipant.position",
        cascade="all, delete-orphan",
    )
    overrides: Mapped[list["ScheduleOverride"]] = relationship(
        back_populates="schedule", order_by="ScheduleOverride.id", cascade="all, delete-orphan"
    )

    __table_args__ = (CheckConstraint("shift_length_days > 0", name="shift_length_positive"),)

    @property
    def users(self) -> list[User]:
        return [participant.user for participant in self.participants]


class ScheduleParticipant(Base):
    __tablename__ = "schedule_participants"

    id: Mapped[int] = mapped_column(primary_key=True)
    schedule_id: Mapped[int] = mapped_column(ForeignKey("schedules.id", ondelete="CASCADE"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    position: Mapped[int] = mapped_column(Integer)

    schedule: Mapped[Schedule] = relationship(back_populates="participants")
    user: Mapped[User] = relationship()

    __table_args__ = (UniqueConstraint("schedule_id", "position"),)


class ScheduleOverride(Base):
    __tablename__ = "schedule_overrides"

    id: Mapped[int] = mapped_column(primary_key=True)
    schedule_id: Mapped[int] = mapped_column(ForeignKey("schedules.id", ondelete="CASCADE"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    starts_at: Mapped[datetime] = mapped_column(UTCDateTime)
    ends_at: Mapped[datetime] = mapped_column(UTCDateTime)

    schedule: Mapped[Schedule] = relationship(back_populates="overrides")
    user: Mapped[User] = relationship()

    __table_args__ = (CheckConstraint("ends_at > starts_at", name="ends_after_start"),)


class EscalationPolicy(Base):
    __tablename__ = "escalation_policies"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)

    levels: Mapped[list["EscalationLevel"]] = relationship(
        back_populates="policy", order_by="EscalationLevel.position", cascade="all, delete-orphan"
    )


class EscalationLevel(Base):
    __tablename__ = "escalation_levels"

    id: Mapped[int] = mapped_column(primary_key=True)
    policy_id: Mapped[int] = mapped_column(ForeignKey("escalation_policies.id", ondelete="CASCADE"))
    position: Mapped[int] = mapped_column(Integer)
    timeout_minutes: Mapped[int] = mapped_column(Integer)

    policy: Mapped[EscalationPolicy] = relationship(back_populates="levels")
    targets: Mapped[list["EscalationTarget"]] = relationship(
        back_populates="level", order_by="EscalationTarget.id", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("policy_id", "position"),
        CheckConstraint("timeout_minutes > 0", name="timeout_positive"),
    )


class EscalationTarget(Base):
    __tablename__ = "escalation_targets"

    id: Mapped[int] = mapped_column(primary_key=True)
    level_id: Mapped[int] = mapped_column(ForeignKey("escalation_levels.id", ondelete="CASCADE"))
    schedule_id: Mapped[int | None] = mapped_column(ForeignKey("schedules.id"))
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))

    level: Mapped[EscalationLevel] = relationship(back_populates="targets")
    schedule: Mapped[Schedule | None] = relationship()
    user: Mapped[User | None] = relationship()

    __table_args__ = (
        CheckConstraint("(schedule_id IS NULL) <> (user_id IS NULL)", name="exactly_one_target"),
    )

    @property
    def schedule_name(self) -> str | None:
        return self.schedule.name if self.schedule else None

    @property
    def user_name(self) -> str | None:
        return self.user.name if self.user else None


class Incident(Base):
    __tablename__ = "incidents"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(500))
    group_key: Mapped[str] = mapped_column(String(64))
    group_labels: Mapped[dict[str, Any]] = mapped_column(JSON)
    severity: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16), default=IncidentStatus.OPEN)
    policy_id: Mapped[int | None] = mapped_column(ForeignKey("escalation_policies.id"))
    # Highest policy level that has been processed so far; 0 before anyone was paged.
    escalation_level: Mapped[int] = mapped_column(Integer, default=0)
    # When the worker should move to the next level. Null means the timer is stopped.
    next_escalation_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    acknowledged_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    acknowledged_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    resolved_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    resolved_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))

    policy: Mapped[EscalationPolicy | None] = relationship()
    acknowledged_by: Mapped[User | None] = relationship(foreign_keys=[acknowledged_by_id])
    resolved_by: Mapped[User | None] = relationship(foreign_keys=[resolved_by_id])
    alerts: Mapped[list["Alert"]] = relationship(
        back_populates="incident", order_by="Alert.id", cascade="all, delete-orphan"
    )
    timeline: Mapped[list["TimelineEvent"]] = relationship(
        back_populates="incident", order_by="TimelineEvent.id", cascade="all, delete-orphan"
    )
    pages: Mapped[list["Page"]] = relationship(
        back_populates="incident", order_by="Page.id", cascade="all, delete-orphan"
    )

    __table_args__ = (
        # At most one unresolved incident per group. This is what makes concurrent webhook
        # deliveries for the same group collapse into one incident instead of two.
        Index(
            "uq_incidents_active_group_key",
            "group_key",
            unique=True,
            postgresql_where=text("status <> 'resolved'"),
            sqlite_where=text("status <> 'resolved'"),
        ),
        Index("ix_incidents_status_next_escalation_at", "status", "next_escalation_at"),
    )

    @property
    def alert_count(self) -> int:
        return len(self.alerts)

    @property
    def firing_alert_count(self) -> int:
        return sum(1 for alert in self.alerts if alert.status == AlertStatus.FIRING)

    @property
    def policy_name(self) -> str | None:
        return self.policy.name if self.policy else None

    @property
    def acknowledged_by_name(self) -> str | None:
        return self.acknowledged_by.name if self.acknowledged_by else None

    @property
    def resolved_by_name(self) -> str | None:
        return self.resolved_by.name if self.resolved_by else None


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(primary_key=True)
    incident_id: Mapped[int] = mapped_column(ForeignKey("incidents.id", ondelete="CASCADE"))
    fingerprint: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16))
    labels: Mapped[dict[str, Any]] = mapped_column(JSON)
    annotations: Mapped[dict[str, Any]] = mapped_column(JSON)
    generator_url: Mapped[str | None] = mapped_column(Text)
    starts_at: Mapped[datetime] = mapped_column(UTCDateTime)
    ends_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_received_at: Mapped[datetime] = mapped_column(UTCDateTime)

    incident: Mapped[Incident] = relationship(back_populates="alerts")

    __table_args__ = (UniqueConstraint("incident_id", "fingerprint"),)


class TimelineEvent(Base):
    __tablename__ = "timeline_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    incident_id: Mapped[int] = mapped_column(
        ForeignKey("incidents.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(32))
    message: Mapped[str] = mapped_column(Text)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)

    incident: Mapped[Incident] = relationship(back_populates="timeline")
    actor: Mapped[User | None] = relationship()

    @property
    def actor_name(self) -> str | None:
        return self.actor.name if self.actor else None


class Page(Base):
    __tablename__ = "pages"

    id: Mapped[int] = mapped_column(primary_key=True)
    incident_id: Mapped[int] = mapped_column(ForeignKey("incidents.id", ondelete="CASCADE"))
    level: Mapped[int] = mapped_column(Integer)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    channel: Mapped[str] = mapped_column(String(16))
    address: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(16), default=PageStatus.PENDING, index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    incident: Mapped[Incident] = relationship(back_populates="pages")
    user: Mapped[User] = relationship()

    # Second line of defence against double paging: even if two workers raced past the row
    # lock, the second insert for the same person, level and channel fails.
    __table_args__ = (UniqueConstraint("incident_id", "level", "user_id", "channel"),)

    @property
    def user_name(self) -> str:
        return self.user.name


class Postmortem(Base):
    __tablename__ = "postmortems"

    id: Mapped[int] = mapped_column(primary_key=True)
    incident_id: Mapped[int] = mapped_column(
        ForeignKey("incidents.id", ondelete="CASCADE"), unique=True
    )
    # TipTap document JSON, stored as-is.
    content: Mapped[dict[str, Any]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(16), default=PostmortemStatus.DRAFT)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime)
    updated_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))

    updated_by: Mapped[User | None] = relationship()

    @property
    def updated_by_name(self) -> str | None:
        return self.updated_by.name if self.updated_by else None
