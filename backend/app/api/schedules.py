from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import AwareDatetime
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, NowDep, PrincipalDep, SessionDep, require_role
from app.auth import Role
from app.models import Schedule, ScheduleOverride, ScheduleParticipant, User
from app.schemas import OnCallOut, OverrideIn, OverrideOut, ScheduleIn, ScheduleOut, ShiftOut
from app.services import schedules

MAX_SHIFT_RANGE = timedelta(days=100)

UNPROCESSABLE = 422

router = APIRouter(
    prefix="/schedules", tags=["schedules"], dependencies=[Depends(require_role(Role.RESPONDER))]
)
manager_only = [Depends(require_role(Role.MANAGER))]


def _get_schedule(session: Session, schedule_id: int) -> Schedule:
    schedule = session.get(Schedule, schedule_id)
    if schedule is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "schedule not found")
    return schedule


def _require_users(session: Session, user_ids: list[int]) -> None:
    known = set(session.scalars(select(User.id).where(User.id.in_(user_ids))))
    missing = sorted(set(user_ids) - known)
    if missing:
        raise HTTPException(UNPROCESSABLE, f"unknown user ids: {missing}")


def _apply(schedule: Schedule, body: ScheduleIn) -> None:
    schedule.name = body.name
    schedule.timezone = body.timezone
    schedule.rotation_start = body.rotation_start
    schedule.shift_length_days = body.shift_length_days
    schedule.participants = [
        ScheduleParticipant(user_id=user_id, position=position)
        for position, user_id in enumerate(body.participant_ids)
    ]


def _commit_or_conflict(session: Session) -> None:
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "schedule name already in use") from exc


@router.get("", response_model=list[ScheduleOut])
def list_schedules(session: SessionDep) -> list[Schedule]:
    return list(session.scalars(select(Schedule).order_by(Schedule.name)))


@router.post(
    "", response_model=ScheduleOut, status_code=status.HTTP_201_CREATED, dependencies=manager_only
)
def create_schedule(body: ScheduleIn, session: SessionDep) -> Schedule:
    _require_users(session, body.participant_ids)
    schedule = Schedule()
    _apply(schedule, body)
    session.add(schedule)
    _commit_or_conflict(session)
    return schedule


@router.get("/{schedule_id}", response_model=ScheduleOut)
def get_schedule(schedule_id: int, session: SessionDep) -> Schedule:
    return _get_schedule(session, schedule_id)


@router.put("/{schedule_id}", response_model=ScheduleOut, dependencies=manager_only)
def update_schedule(schedule_id: int, body: ScheduleIn, session: SessionDep) -> Schedule:
    schedule = _get_schedule(session, schedule_id)
    _require_users(session, body.participant_ids)
    # Flush the removal of the old participants first so the new rows do not collide with
    # them on (schedule_id, position).
    schedule.participants = []
    session.flush()
    _apply(schedule, body)
    _commit_or_conflict(session)
    return schedule


@router.get("/{schedule_id}/on-call", response_model=OnCallOut)
def on_call(
    schedule_id: int, session: SessionDep, now: NowDep, at: AwareDatetime | None = None
) -> OnCallOut:
    schedule = _get_schedule(session, schedule_id)
    current = schedules.on_call_at(schedule, at or now)
    if current is None:
        return OnCallOut(user=None, source=None)
    return OnCallOut(user=session.get_one(User, current.user_id), source=current.source)


@router.get("/{schedule_id}/shifts", response_model=list[ShiftOut])
def list_shifts(
    schedule_id: int,
    session: SessionDep,
    start: Annotated[AwareDatetime, Query()],
    end: Annotated[AwareDatetime, Query()],
) -> list[ShiftOut]:
    if end <= start or end - start > MAX_SHIFT_RANGE:
        raise HTTPException(
            UNPROCESSABLE,
            f"end must be after start and within {MAX_SHIFT_RANGE.days} days of it",
        )
    schedule = _get_schedule(session, schedule_id)
    shifts = schedules.shifts_between(schedule, start, end)
    users = {
        user.id: user
        for user in session.scalars(select(User).where(User.id.in_({s.user_id for s in shifts})))
    }
    return [
        ShiftOut(
            user=users[shift.user_id],
            source=shift.source,
            starts_at=shift.starts_at,
            ends_at=shift.ends_at,
        )
        for shift in shifts
    ]


@router.post(
    "/{schedule_id}/overrides", response_model=OverrideOut, status_code=status.HTTP_201_CREATED
)
def create_override(
    schedule_id: int,
    body: OverrideIn,
    session: SessionDep,
    user: CurrentUser,
    principal: PrincipalDep,
) -> ScheduleOverride:
    # Responders may take a shift themselves; putting someone else on call needs a manager.
    if body.user_id != user.id and not principal.has_role(Role.MANAGER):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "responders can only create overrides for themselves"
        )
    schedule = _get_schedule(session, schedule_id)
    _require_users(session, [body.user_id])
    override = ScheduleOverride(
        user_id=body.user_id, starts_at=body.starts_at, ends_at=body.ends_at
    )
    schedule.overrides.append(override)
    session.commit()
    return override


@router.delete(
    "/{schedule_id}/overrides/{override_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=manager_only,
)
def delete_override(schedule_id: int, override_id: int, session: SessionDep) -> Response:
    override = session.get(ScheduleOverride, override_id)
    if override is None or override.schedule_id != schedule_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "override not found")
    session.delete(override)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
