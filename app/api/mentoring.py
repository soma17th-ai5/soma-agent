"""멘토링 액션 엔드포인트. SPEC §4.4 needs_confirmation 흐름.

- POST /api/v1/mentoring/{id}/apply  body: {confirmed?: bool}
  * confirmed=false (기본): ActionProposal 반환 — 실제 신청 안 함
  * confirmed=true: 직전 mentoring.get 재검증 후 sidecar apply → ActionResult
- POST /api/v1/mentoring/cancel       body: {apply_sn, qustnr_sn, confirmed?: bool}
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app.adapters.opensoma_client import OpenSomaClientError
from app.api.deps import DbSession, SessionId, SomaClient, session_expired_exc
from app.domain.contracts.action import ActionProposal, ActionResult
from app.observability.logging import get_logger
from app.services import mentoring as mentoring_service

router = APIRouter(prefix="/api/v1/mentoring", tags=["mentoring"])
log = get_logger("app.api.mentoring")


class ApplyRequest(BaseModel):
    confirmed: bool = Field(default=False)
    soma_user_id: str = Field(min_length=1)


class CancelRequest(BaseModel):
    apply_sn: int = Field(gt=0)
    qustnr_sn: int = Field(gt=0)
    confirmed: bool = Field(default=False)
    soma_user_id: str = Field(min_length=1)


def _map_error(err: OpenSomaClientError) -> HTTPException:
    if err.status == 401:
        if err.code == "SESSION_EXPIRED":
            return session_expired_exc()
        return HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": err.code, "message": err.message},
        )
    if err.status in (404, 422):
        return HTTPException(
            status_code=err.status,
            detail={"code": err.code, "message": err.message},
        )
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={"code": "UPSTREAM_UNAVAILABLE", "message": "OpenSoma is temporarily unavailable"},
    )


@router.post("/{mentoring_id}/apply")
def apply(
    mentoring_id: int,
    body: ApplyRequest,
    session_id: SessionId,
    db: DbSession,
    client: SomaClient,
) -> ActionProposal | ActionResult:
    if mentoring_id <= 0:
        raise HTTPException(
            status_code=422,
            detail={"code": "INVALID_REQUEST", "message": "mentoring_id must be positive"},
        )
    try:
        return mentoring_service.apply(
            db,
            client,
            session_id,
            body.soma_user_id,
            mentoring_id,
            confirmed=body.confirmed,
        )
    except mentoring_service.MentoringNotApplicableError as err:
        log.info(
            "mentoring.apply.not_applicable",
            mentoring_id=mentoring_id,
            current_status=err.status,
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "MENTORING_NOT_OPEN",
                "message": f"멘토링이 신청 가능 상태가 아닙니다 (현재: {err.status!r})",
            },
        ) from err
    except OpenSomaClientError as err:
        raise _map_error(err) from err


@router.post("/cancel")
def cancel(
    body: CancelRequest,
    session_id: SessionId,
    db: DbSession,
    client: SomaClient,
) -> ActionProposal | ActionResult:
    try:
        return mentoring_service.cancel(
            db,
            client,
            session_id,
            body.soma_user_id,
            apply_sn=body.apply_sn,
            qustnr_sn=body.qustnr_sn,
            confirmed=body.confirmed,
        )
    except OpenSomaClientError as err:
        raise _map_error(err) from err
