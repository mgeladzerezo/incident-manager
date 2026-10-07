from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import CurrentUser, NowDep, PrincipalDep, SessionDep, require_role
from app.auth import Role
from app.models import Incident, IncidentStatus, Postmortem, PostmortemStatus
from app.schemas import IncidentDetail, IncidentSummary, NoteIn, PostmortemIn, PostmortemOut
from app.services import incidents

router = APIRouter(
    prefix="/incidents", tags=["incidents"], dependencies=[Depends(require_role(Role.RESPONDER))]
)


def _get_incident(session: Session, incident_id: int, lock: bool = False) -> Incident:
    query = select(Incident).where(Incident.id == incident_id)
    if lock:
        # Serialises acknowledge/resolve against the escalation worker.
        query = query.with_for_update()
    incident = session.scalars(query).first()
    if incident is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "incident not found")
    return incident


@router.get("", response_model=list[IncidentSummary])
def list_incidents(
    session: SessionDep,
    status_filter: Annotated[IncidentStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
) -> list[Incident]:
    query = (
        select(Incident)
        .options(selectinload(Incident.alerts))
        .order_by(Incident.created_at.desc(), Incident.id.desc())
        .limit(limit)
    )
    if status_filter is not None:
        query = query.where(Incident.status == status_filter)
    return list(session.scalars(query))


@router.get("/{incident_id}", response_model=IncidentDetail)
def get_incident(incident_id: int, session: SessionDep) -> Incident:
    return _get_incident(session, incident_id)


@router.post("/{incident_id}/acknowledge", response_model=IncidentDetail)
def acknowledge(incident_id: int, session: SessionDep, user: CurrentUser, now: NowDep) -> Incident:
    incident = _get_incident(session, incident_id, lock=True)
    try:
        incidents.acknowledge(incident, user, now)
    except incidents.InvalidTransition as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    session.commit()
    return incident


@router.post("/{incident_id}/resolve", response_model=IncidentDetail)
def resolve(incident_id: int, session: SessionDep, user: CurrentUser, now: NowDep) -> Incident:
    incident = _get_incident(session, incident_id, lock=True)
    incidents.resolve(incident, user, now)
    session.commit()
    return incident


@router.post("/{incident_id}/notes", response_model=IncidentDetail)
def add_note(
    incident_id: int, body: NoteIn, session: SessionDep, user: CurrentUser, now: NowDep
) -> Incident:
    incident = _get_incident(session, incident_id)
    incidents.add_note(incident, user, body.text, now)
    session.commit()
    return incident


@router.get("/{incident_id}/postmortem", response_model=PostmortemOut)
def get_postmortem(incident_id: int, session: SessionDep) -> Postmortem:
    postmortem = _find_postmortem(session, incident_id)
    if postmortem is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no postmortem yet")
    return postmortem


@router.put("/{incident_id}/postmortem", response_model=PostmortemOut)
def save_postmortem(
    incident_id: int,
    body: PostmortemIn,
    session: SessionDep,
    user: CurrentUser,
    principal: PrincipalDep,
    now: NowDep,
) -> Postmortem:
    _get_incident(session, incident_id)
    postmortem = _find_postmortem(session, incident_id)
    published = body.status == PostmortemStatus.PUBLISHED or (
        postmortem is not None and postmortem.status == PostmortemStatus.PUBLISHED
    )
    # Anyone on the team can draft; publishing and editing a published document is a
    # manager decision.
    if published and not principal.has_role(Role.MANAGER):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "requires role manager")

    if postmortem is None:
        postmortem = Postmortem(incident_id=incident_id)
        session.add(postmortem)
    postmortem.content = body.content
    postmortem.status = body.status
    postmortem.updated_at = now
    postmortem.updated_by = user
    session.commit()
    return postmortem


def _find_postmortem(session: Session, incident_id: int) -> Postmortem | None:
    return session.scalars(select(Postmortem).where(Postmortem.incident_id == incident_id)).first()
