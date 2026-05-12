"""멘토링 액션 엔드포인트.

- POST /api/v1/mentoring/{id}/apply  body: {soma_user_id}
  * 직전 mentoring.get 재검증 후 sidecar apply → ActionResult
- POST /api/v1/mentoring/cancel       body: {apply_sn, qustnr_sn, soma_user_id}

도메인/업스트림 예외는 raise만 하면 app-level 핸들러가 표준 응답으로 변환한다.
"""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.api.deps import DbSession, SessionId, SomaClient
from app.domain.contracts.action import ActionResult
from app.errors.exceptions import InvalidRequest
from app.observability.logging import get_logger
from app.services import mentoring as mentoring_service

router = APIRouter(prefix="/api/v1/mentoring", tags=["mentoring"])
log = get_logger("app.api.mentoring")


class ApplyRequest(BaseModel):
    soma_user_id: str = Field(min_length=1)


class CancelRequest(BaseModel):
    apply_sn: int = Field(gt=0)
    qustnr_sn: int = Field(gt=0)
    soma_user_id: str = Field(min_length=1)


@router.post("/{mentoring_id}/apply")
def apply(
    mentoring_id: int,
    body: ApplyRequest,
    session_id: SessionId,
    db: DbSession,
    client: SomaClient,
) -> ActionResult:
    if mentoring_id <= 0:
        raise InvalidRequest("mentoring_id must be positive")
    result = mentoring_service.apply(
        db,
        client,
        session_id,
        body.soma_user_id,
        mentoring_id,
        confirmed=True,
    )
    if not isinstance(result, ActionResult):
        raise InvalidRequest("unexpected mentoring apply proposal")
    return result


@router.post("/cancel")
def cancel(
    body: CancelRequest,
    session_id: SessionId,
    db: DbSession,
    client: SomaClient,
) -> ActionResult:
    result = mentoring_service.cancel(
        db,
        client,
        session_id,
        body.soma_user_id,
        apply_sn=body.apply_sn,
        qustnr_sn=body.qustnr_sn,
        confirmed=True,
    )
    if not isinstance(result, ActionResult):
        raise InvalidRequest("unexpected mentoring cancel proposal")
    return result
