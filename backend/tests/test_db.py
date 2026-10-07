from datetime import UTC, datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.db import normalize_url
from app.models import User


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("postgresql://u:p@db-rw:5432/app", "postgresql+psycopg://u:p@db-rw:5432/app"),
        ("postgres://u:p@db-rw:5432/app", "postgresql+psycopg://u:p@db-rw:5432/app"),
        ("postgresql+psycopg://u:p@db/app", "postgresql+psycopg://u:p@db/app"),
        ("sqlite://", "sqlite://"),
    ],
)
def test_plain_postgres_urls_are_pointed_at_psycopg(given, expected):
    assert normalize_url(given) == expected


def test_datetimes_are_stored_as_utc_and_come_back_aware(session):
    zagreb_noon = datetime(2026, 7, 1, 12, 0, tzinfo=timezone(timedelta(hours=2)))
    session.add(User(email="a@example.com", name="A", created_at=zagreb_noon))
    session.commit()
    session.expire_all()

    stored = session.scalars(select(User)).one().created_at

    assert stored == datetime(2026, 7, 1, 10, 0, tzinfo=UTC)
    assert stored.utcoffset() == timedelta(0)


def test_naive_datetimes_are_refused(session):
    session.add(User(email="a@example.com", name="A", created_at=datetime(2026, 7, 1, 12, 0)))  # noqa: DTZ001

    with pytest.raises(Exception, match="naive datetime"):
        session.flush()
