from dataclasses import asdict

from fastapi import APIRouter, Depends

from app.api.deps import NotifiersDep, NowDep, SessionDep, SettingsDep, verify_webhook_token
from app.schemas import IngestOut
from app.services import alerts

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post(
    "/alertmanager", response_model=IngestOut, dependencies=[Depends(verify_webhook_token)]
)
def receive_alertmanager(
    payload: alerts.AlertmanagerWebhook,
    session: SessionDep,
    settings: SettingsDep,
    notifiers: NotifiersDep,
    now: NowDep,
) -> IngestOut:
    result = alerts.ingest(session, payload, settings.grouping_labels, notifiers, now)
    session.commit()
    return IngestOut(**asdict(result))
