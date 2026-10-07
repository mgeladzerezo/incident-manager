from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.auth import TokenVerifier
from app.config import Settings
from app.db import Base, make_engine, make_session_factory
from app.main import create_app
from app.models import (
    EscalationLevel,
    EscalationPolicy,
    EscalationTarget,
    Schedule,
    ScheduleParticipant,
    User,
)
from app.notifications import NotifyError, PageMessage

ISSUER = "https://keycloak.test/realms/incident"
AUDIENCE = "incident-manager"
WEBHOOK_TOKEN = "test-webhook-token"
T0 = datetime(2026, 3, 2, 12, 0, tzinfo=UTC)


class FakeClock:
    def __init__(self, now: datetime = T0) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now

    def advance(self, **delta: float) -> datetime:
        self._now += timedelta(**delta)
        return self._now


class RecordingNotifier:
    """Stands in for Slack/Telegram/email: remembers what it was asked to send."""

    def __init__(self, channel: str = "slack", attribute: str = "slack_user_id") -> None:
        self.channel = channel
        self._attribute = attribute
        self.sent: list[tuple[str, PageMessage]] = []
        self.failing = False

    def address_for(self, user: User) -> str | None:
        return getattr(user, self._attribute)

    def send(self, address: str, message: PageMessage) -> None:
        if self.failing:
            raise NotifyError(f"{self.channel}: simulated outage")
        self.sent.append((address, message))


class StaticKeyProvider:
    def __init__(self, public_key) -> None:
        self._public_key = public_key

    def signing_key(self, token: str):
        return self._public_key


@pytest.fixture(scope="session")
def signing_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def session_factory() -> Iterator[sessionmaker[Session]]:
    engine = make_engine("sqlite://")
    Base.metadata.create_all(engine)
    yield make_session_factory(engine)
    engine.dispose()


@pytest.fixture
def session(session_factory) -> Iterator[Session]:
    with session_factory() as session:
        yield session


@pytest.fixture
def notifier() -> RecordingNotifier:
    return RecordingNotifier()


@pytest.fixture
def settings() -> Settings:
    return Settings(
        _env_file=None,
        database_url="sqlite://",
        webhook_token=WEBHOOK_TOKEN,
        oidc_issuer=ISSUER,
        oidc_audience=AUDIENCE,
        public_url="https://incidents.test",
    )


@pytest.fixture
def verifier(signing_key) -> TokenVerifier:
    return TokenVerifier(ISSUER, AUDIENCE, StaticKeyProvider(signing_key.public_key()))


@pytest.fixture
def client(settings, session_factory, clock, verifier, notifier) -> Iterator[TestClient]:
    app = create_app(
        settings=settings,
        session_factory=session_factory,
        clock=clock,
        verifier=verifier,
        notifiers=[notifier],
    )
    with TestClient(app) as test_client:
        yield test_client


TokenFactory = Callable[..., str]


@pytest.fixture
def make_token(signing_key) -> TokenFactory:
    def build(
        *roles: str,
        sub: str = "kc-user-1",
        email: str = "alice@example.com",
        name: str = "Alice",
        key=None,
        **overrides,
    ) -> str:
        now = datetime.now(UTC)
        claims = {
            "iss": ISSUER,
            "aud": AUDIENCE,
            "sub": sub,
            "email": email,
            "name": name,
            "iat": now,
            "exp": now + timedelta(minutes=5),
            "realm_access": {"roles": list(roles)},
        }
        claims.update(overrides)
        return jwt.encode(claims, key or signing_key, algorithm="RS256")

    return build


@pytest.fixture
def auth(make_token) -> Callable[..., dict[str, str]]:
    def headers(*roles: str, **claims) -> dict[str, str]:
        return {"Authorization": f"Bearer {make_token(*roles, **claims)}"}

    return headers


WEBHOOK_AUTH = {"Authorization": f"Bearer {WEBHOOK_TOKEN}"}


def make_user(session: Session, name: str, **fields) -> User:
    user = User(
        email=f"{name.lower()}@example.com",
        name=name,
        slack_user_id=f"U-{name.upper()}",
        created_at=T0,
        **fields,
    )
    session.add(user)
    session.flush()
    return user


def make_schedule(
    session: Session,
    users: list[User],
    name: str = "primary",
    timezone: str = "UTC",
    rotation_start: datetime = datetime(2026, 1, 5, 9, 0),  # noqa: DTZ001 - local wall time
    shift_length_days: int = 7,
) -> Schedule:
    schedule = Schedule(
        name=name,
        timezone=timezone,
        rotation_start=rotation_start,
        shift_length_days=shift_length_days,
        participants=[
            ScheduleParticipant(user=user, position=position) for position, user in enumerate(users)
        ],
    )
    session.add(schedule)
    session.flush()
    return schedule


def make_policy(
    session: Session,
    levels: list[tuple[int, list[User | Schedule]]],
    name: str = "default",
    is_default: bool = True,
) -> EscalationPolicy:
    """`levels` is a list of (timeout_minutes, targets), level 1 first."""
    policy = EscalationPolicy(
        name=name,
        is_default=is_default,
        levels=[
            EscalationLevel(
                position=position,
                timeout_minutes=timeout,
                targets=[
                    EscalationTarget(user=t)
                    if isinstance(t, User)
                    else EscalationTarget(schedule=t)
                    for t in targets
                ],
            )
            for position, (timeout, targets) in enumerate(levels, start=1)
        ],
    )
    session.add(policy)
    session.flush()
    return policy


def alert(
    status: str = "firing",
    alertname: str = "HighErrorRate",
    service: str = "checkout",
    instance: str = "web-1",
    fingerprint: str | None = None,
    **labels: str,
) -> dict:
    """One alert in Alertmanager webhook format."""
    body = {
        "status": status,
        "labels": {
            "alertname": alertname,
            "service": service,
            "instance": instance,
            "severity": "critical",
            **labels,
        },
        "annotations": {"summary": f"{alertname} on {service}"},
        "startsAt": "2026-03-02T11:58:00Z",
        "endsAt": "2026-03-02T12:05:00Z" if status == "resolved" else "0001-01-01T00:00:00Z",
        "generatorURL": "http://prometheus.test/graph",
    }
    if fingerprint is not None:
        body["fingerprint"] = fingerprint
    return body


def webhook(*alerts: dict) -> dict:
    return {"version": "4", "status": "firing", "receiver": "incident-manager", "alerts": alerts}
