from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.deps import CurrentUser, NowDep, PrincipalDep, SessionDep, require_role
from app.auth import Role
from app.models import User
from app.schemas import MeOut, UserCreate, UserOut, UserUpdate

router = APIRouter(tags=["users"], dependencies=[Depends(require_role(Role.RESPONDER))])


@router.get("/me", response_model=MeOut)
def me(user: CurrentUser, principal: PrincipalDep) -> MeOut:
    return MeOut(user=UserOut.model_validate(user), roles=sorted(principal.roles))


@router.get("/users", response_model=list[UserOut])
def list_users(session: SessionDep) -> list[User]:
    return list(session.scalars(select(User).order_by(User.name)))


@router.post(
    "/users",
    response_model=UserOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_role(Role.ADMIN))],
)
def create_user(body: UserCreate, session: SessionDep, now: NowDep) -> User:
    user = User(**body.model_dump(), created_at=now)
    session.add(user)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "email already in use") from exc
    return user


@router.patch("/users/{user_id}", response_model=UserOut)
def update_user(
    user_id: int,
    body: UserUpdate,
    session: SessionDep,
    current: CurrentUser,
    principal: PrincipalDep,
) -> User:
    # Everyone maintains their own contact details; changing someone else's is an admin task.
    if user_id != current.id and not principal.has_role(Role.ADMIN):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "requires role admin")
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "user not found")
    changes = body.model_dump(exclude_unset=True)
    if changes.get("name") is None:
        changes.pop("name", None)
    for field, value in changes.items():
        setattr(user, field, value)
    session.commit()
    return user
