"""멘토링 액션 엔드포인트. SPEC §4.4 needs_confirmation 흐름.

- POST /api/v1/mentoring/{id}/apply  body: {confirmed?: bool}
  * confirmed=false (기본): ActionProposal 반환 — 실제 신청 안 함
  * confirmed=true: 직전 mentoring.get 재검증 후 sidecar apply → ActionResult
- POST /api/v1/mentoring/cancel       body: {apply_sn, qustnr_sn, confirmed?: bool}

도메인/업스트림 예외는 raise만 하면 app-level 핸들러가 표준 응답으로 변환한다.
Request 스키마는 `app.domain.schemas.mentoring`, Response DTO는 `app.domain.dtos.action`.
"""
from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import DbSession, SessionId, SomaClient
from app.domain.dtos.action import ActionProposal, ActionResult
from app.domain.schemas.mentoring import ApplyReq, CancelReq
from app.errors.exceptions import InvalidRequest
from app.observability.logging import get_logger
from app.services import mentoring as mentoring_service

router = APIRouter(prefix="/api/v1/mentoring", tags=["mentoring"])
log = get_logger("app.api.mentoring")


@router.post("/{mentoring_id}/apply", response_model=ActionProposal | ActionResult)
def apply(
    mentoring_id: int,
    body: ApplyReq,
    session_id: SessionId,
    db: DbSession,
    client: SomaClient,
) -> ActionProposal | ActionResult:
    if mentoring_id <= 0:
        raise InvalidRequest("mentoring_id must be positive")
    return mentoring_service.apply(
        db,
        client,
        session_id,
        body.soma_user_id,
        mentoring_id,
        confirmed=body.confirmed,
    )


@router.post("/cancel", response_model=ActionProposal | ActionResult)
def cancel(
    body: CancelReq,
    session_id: SessionId,
    db: DbSession,
    client: SomaClient,
) -> ActionProposal | ActionResult:
    return mentoring_service.cancel(
        db,
        client,
        session_id,
        body.soma_user_id,
        apply_sn=body.apply_sn,
        qustnr_sn=body.qustnr_sn,
        confirmed=body.confirmed,
    )
