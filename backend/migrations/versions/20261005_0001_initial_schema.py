"""initial schema

Revision ID: 0001
Revises:
"""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "escalation_policies",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_escalation_policies")),
        sa.UniqueConstraint("name", name=op.f("uq_escalation_policies_name")),
    )
    op.create_table(
        "schedules",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("rotation_start", sa.DateTime(), nullable=False),
        sa.Column("shift_length_days", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "shift_length_days > 0", name=op.f("ck_schedules_shift_length_positive")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_schedules")),
        sa.UniqueConstraint("name", name=op.f("uq_schedules_name")),
    )
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=True),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("slack_user_id", sa.String(length=64), nullable=True),
        sa.Column("telegram_chat_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
        sa.UniqueConstraint("subject", name=op.f("uq_users_subject")),
    )
    op.create_table(
        "escalation_levels",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("policy_id", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("timeout_minutes", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "timeout_minutes > 0", name=op.f("ck_escalation_levels_timeout_positive")
        ),
        sa.ForeignKeyConstraint(
            ["policy_id"],
            ["escalation_policies.id"],
            name=op.f("fk_escalation_levels_policy_id_escalation_policies"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_escalation_levels")),
        sa.UniqueConstraint("policy_id", "position", name=op.f("uq_escalation_levels_policy_id")),
    )
    op.create_table(
        "incidents",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("group_key", sa.String(length=64), nullable=False),
        sa.Column("group_labels", sa.JSON(), nullable=False),
        sa.Column("severity", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("policy_id", sa.Integer(), nullable=True),
        sa.Column("escalation_level", sa.Integer(), nullable=False),
        sa.Column("next_escalation_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("acknowledged_by_id", sa.Integer(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["acknowledged_by_id"], ["users.id"], name=op.f("fk_incidents_acknowledged_by_id_users")
        ),
        sa.ForeignKeyConstraint(
            ["policy_id"],
            ["escalation_policies.id"],
            name=op.f("fk_incidents_policy_id_escalation_policies"),
        ),
        sa.ForeignKeyConstraint(
            ["resolved_by_id"], ["users.id"], name=op.f("fk_incidents_resolved_by_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_incidents")),
    )
    op.create_index(
        "ix_incidents_status_next_escalation_at",
        "incidents",
        ["status", "next_escalation_at"],
        unique=False,
    )
    op.create_index(
        "uq_incidents_active_group_key",
        "incidents",
        ["group_key"],
        unique=True,
        postgresql_where=sa.text("status <> 'resolved'"),
        sqlite_where=sa.text("status <> 'resolved'"),
    )
    op.create_table(
        "schedule_overrides",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("schedule_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "ends_at > starts_at", name=op.f("ck_schedule_overrides_ends_after_start")
        ),
        sa.ForeignKeyConstraint(
            ["schedule_id"],
            ["schedules.id"],
            name=op.f("fk_schedule_overrides_schedule_id_schedules"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_schedule_overrides_user_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_schedule_overrides")),
    )
    op.create_table(
        "schedule_participants",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("schedule_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["schedule_id"],
            ["schedules.id"],
            name=op.f("fk_schedule_participants_schedule_id_schedules"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_schedule_participants_user_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_schedule_participants")),
        sa.UniqueConstraint(
            "schedule_id", "position", name=op.f("uq_schedule_participants_schedule_id")
        ),
    )
    op.create_table(
        "alerts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("incident_id", sa.Integer(), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("labels", sa.JSON(), nullable=False),
        sa.Column("annotations", sa.JSON(), nullable=False),
        sa.Column("generator_url", sa.Text(), nullable=True),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_received_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["incident_id"],
            ["incidents.id"],
            name=op.f("fk_alerts_incident_id_incidents"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_alerts")),
        sa.UniqueConstraint("incident_id", "fingerprint", name=op.f("uq_alerts_incident_id")),
    )
    op.create_table(
        "escalation_targets",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("level_id", sa.Integer(), nullable=False),
        sa.Column("schedule_id", sa.Integer(), nullable=True),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.CheckConstraint(
            "(schedule_id IS NULL) <> (user_id IS NULL)",
            name=op.f("ck_escalation_targets_exactly_one_target"),
        ),
        sa.ForeignKeyConstraint(
            ["level_id"],
            ["escalation_levels.id"],
            name=op.f("fk_escalation_targets_level_id_escalation_levels"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["schedule_id"],
            ["schedules.id"],
            name=op.f("fk_escalation_targets_schedule_id_schedules"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_escalation_targets_user_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_escalation_targets")),
    )
    op.create_table(
        "pages",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("incident_id", sa.Integer(), nullable=False),
        sa.Column("level", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("channel", sa.String(length=16), nullable=False),
        sa.Column("address", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["incident_id"],
            ["incidents.id"],
            name=op.f("fk_pages_incident_id_incidents"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_pages_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_pages")),
        sa.UniqueConstraint(
            "incident_id", "level", "user_id", "channel", name=op.f("uq_pages_incident_id")
        ),
    )
    op.create_index(op.f("ix_pages_status"), "pages", ["status"], unique=False)
    op.create_table(
        "postmortems",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("incident_id", sa.Integer(), nullable=False),
        sa.Column("content", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["incident_id"],
            ["incidents.id"],
            name=op.f("fk_postmortems_incident_id_incidents"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_id"], ["users.id"], name=op.f("fk_postmortems_updated_by_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_postmortems")),
        sa.UniqueConstraint("incident_id", name=op.f("uq_postmortems_incident_id")),
    )
    op.create_table(
        "timeline_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("incident_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("actor_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["actor_id"], ["users.id"], name=op.f("fk_timeline_events_actor_id_users")
        ),
        sa.ForeignKeyConstraint(
            ["incident_id"],
            ["incidents.id"],
            name=op.f("fk_timeline_events_incident_id_incidents"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_timeline_events")),
    )
    op.create_index(
        op.f("ix_timeline_events_incident_id"), "timeline_events", ["incident_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_timeline_events_incident_id"), table_name="timeline_events")
    op.drop_table("timeline_events")
    op.drop_table("postmortems")
    op.drop_index(op.f("ix_pages_status"), table_name="pages")
    op.drop_table("pages")
    op.drop_table("escalation_targets")
    op.drop_table("alerts")
    op.drop_table("schedule_participants")
    op.drop_table("schedule_overrides")
    op.drop_index(
        "uq_incidents_active_group_key",
        table_name="incidents",
        postgresql_where=sa.text("status <> 'resolved'"),
        sqlite_where=sa.text("status <> 'resolved'"),
    )
    op.drop_index("ix_incidents_status_next_escalation_at", table_name="incidents")
    op.drop_table("incidents")
    op.drop_table("escalation_levels")
    op.drop_table("users")
    op.drop_table("schedules")
    op.drop_table("escalation_policies")
