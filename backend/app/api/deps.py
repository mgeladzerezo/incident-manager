import hmac
from collections.abc import Callable, Iterator
from datetime import datetime
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import InvalidToken, Principal, Role
from app.config import Settings
from app.models import User
from app.notifications import Notifier

_bearer = HTTPBearer(auto_error=False)
Credentials = Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)]


def get_session(request: Request) -> Iterator[Session]:
    with request.app.state.session_factory() as session:
        yield session


def get_now(request: Request) -> datetime:
    return request.app.state.clock.now()


def get_app_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_notifiers(request: Request) -> list[Notifier]:
    return request.app.state.notifiers


SessionDep = Annotated[Session, Depends(get_session)]
NowDep = Annotated[datetime, Depends(get_now)]
SettingsDep = Annotated[Settings, Depends(get_app_settings)]
NotifiersDep = Annotated[list[Notifier], Depends(get_notifiers)]


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status.HTTP_401_UNAUTHORIZED, detail, headers={"WWW-Authenticate": "Bearer"}
    )


def get_principal(request: Request, credentials: Credentials) -> Principal:
    if credentials is None:
        raise _unauthorized("missing bearer token")
    try:
        principal = request.app.state.verifier.verify(credentials.credentials)
    except InvalidToken as exc:
        raise _unauthorized("invalid token") from exc
    if not principal.roles:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "no role assigned")
    return principal


PrincipalDep = Annotated[Principal, Depends(get_principal)]


def require_role(role: Role) -> Callable[[Principal], Principal]:
    def check(principal: PrincipalDep) -> Principal:
        if not principal.has_role(role):
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"requires role {role.value}")
        return principal

    return check


def get_current_user(principal: PrincipalDep, session: SessionDep, now: NowDep) -> User:
    """The database row for the caller, created on first login."""
    user = _find_by_subject(session, principal.subject)
    if user is not None:
        return user

    # Pre-created by an admin so they could be scheduled before logging in: adopt the row.
    user = session.scalars(
        select(User).where(User.email == principal.email, User.subject.is_(None))
    ).first()
    if user is not None:
        user.subject = principal.subject
        session.commit()
        return user

    try:
        session.add(
            User(
                subject=principal.subject,
                email=principal.email,
                name=principal.name,
                created_at=now,
            )
        )
        session.commit()
    except IntegrityError as exc:
        # A parallel first request from the same person inserted the row, or the email
        # belongs to a different subject.
        session.rollback()
        if _find_by_subject(session, principal.subject) is None:
            raise HTTPException(
                status.HTTP_409_CONFLICT, "email is already linked to another account"
            ) from exc
    return _find_by_subject(session, principal.subject)


def _find_by_subject(session: Session, subject: str) -> User | None:
    return session.scalars(select(User).where(User.subject == subject)).first()


CurrentUser = Annotated[User, Depends(get_current_user)]


def verify_webhook_token(credentials: Credentials, settings: SettingsDep) -> None:
    expected = settings.webhook_token
    presented = credentials.credentials if credentials else ""
    # An unset token must not mean "open to everyone".
    if not expected or not hmac.compare_digest(presented.encode(), expected.encode()):
        raise _unauthorized("invalid webhook token")
