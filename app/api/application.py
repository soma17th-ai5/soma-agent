"""사용자 접수 내역 조회. TTL 캐시 우선 + force_refresh 옵션.

업스트림 예외는 raise만 — app-level 핸들러가 표준 응답으로 변환한다.
"""
from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import DbSession, SessionId, SomaClient
from app.domain.schemas.application import HistoryResp
from app.observability.logging import get_logger
from app.services import application as application_service

router = APIRouter(prefix="/api/v1/applications", tags=["applications"])
log = get_logger("app.api.application")


@router.get("")
def list_history(
    session_id: SessionId,
    db: DbSession,
    client: SomaClient,
    soma_user_id: str,
    force_refresh: bool = False,
) -> HistoryResp:
    dto = application_service.get_history(
        db, client, session_id, soma_user_id, force_refresh=force_refresh
    )
    return HistoryResp.from_dto(dto)
