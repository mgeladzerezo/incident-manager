from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import SessionDep, require_role
from app.auth import Role
from app.models import EscalationLevel, EscalationPolicy, EscalationTarget, Schedule, User
from app.schemas import PolicyIn, PolicyOut

UNPROCESSABLE = 422

router = APIRouter(
    prefix="/escalation-policies",
    tags=["escalation policies"],
    dependencies=[Depends(require_role(Role.RESPONDER))],
)
manager_only = [Depends(require_role(Role.MANAGER))]


def _validate_targets(session: Session, body: PolicyIn) -> None:
    targets = [target for level in body.levels for target in level.targets]
    for model, ids in (
        (Schedule, {t.schedule_id for t in targets if t.schedule_id is not None}),
        (User, {t.user_id for t in targets if t.user_id is not None}),
    ):
        known = set(session.scalars(select(model.id).where(model.id.in_(ids))))
        if ids - known:
            raise HTTPException(
                UNPROCESSABLE,
                f"unknown {model.__tablename__} ids: {sorted(ids - known)}",
            )


def _apply(session: Session, policy: EscalationPolicy, body: PolicyIn) -> None:
    if body.is_default:
        session.execute(update(EscalationPolicy).values(is_default=False))
    policy.name = body.name
    policy.is_default = body.is_default
    policy.levels = [
        EscalationLevel(
            position=position,
            timeout_minutes=level.timeout_minutes,
            targets=[
                EscalationTarget(schedule_id=t.schedule_id, user_id=t.user_id)
                for t in level.targets
            ],
        )
        for position, level in enumerate(body.levels, start=1)
    ]


def _commit_or_conflict(session: Session) -> None:
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "policy name already in use") from exc


@router.get("", response_model=list[PolicyOut])
def list_policies(session: SessionDep) -> list[EscalationPolicy]:
    return list(session.scalars(select(EscalationPolicy).order_by(EscalationPolicy.name)))


@router.post(
    "", response_model=PolicyOut, status_code=status.HTTP_201_CREATED, dependencies=manager_only
)
def create_policy(body: PolicyIn, session: SessionDep) -> EscalationPolicy:
    _validate_targets(session, body)
    policy = EscalationPolicy()
    _apply(session, policy, body)
    session.add(policy)
    _commit_or_conflict(session)
    return policy


@router.put("/{policy_id}", response_model=PolicyOut, dependencies=manager_only)
def update_policy(policy_id: int, body: PolicyIn, session: SessionDep) -> EscalationPolicy:
    policy = session.get(EscalationPolicy, policy_id)
    if policy is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "policy not found")
    _validate_targets(session, body)
    policy.levels = []
    session.flush()
    _apply(session, policy, body)
    _commit_or_conflict(session)
    return policy
