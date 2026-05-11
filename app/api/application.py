"""사용자 접수 내역 조회. TTL 캐시 우선 + force_refresh 옵션.

업스트림 예외는 raise만 — app-level 핸들러가 표준 응답으로 변환한다.
"""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from app.api.deps import DbSession, SessionId, SomaClient
from app.observability.logging import get_logger
from app.services import application as application_service

router = APIRouter(prefix="/api/v1/applications", tags=["applications"])
log = get_logger("app.api.application")


class HistoryItem(BaseModel):
    apply_sn: int
    qustnr_sn: int | None
    category: str | None
    title: str | None
    target_url: str | None
    author: str | None
    session_date_text: str | None
    applied_at_text: str | None
    application_status: str | None
    approval_status: str | None


class HistoryResponse(BaseModel):
    items: list[HistoryItem]
    cached_at: str
    refreshed: bool


@router.get("")
def list_history(
    session_id: SessionId,
    db: DbSession,
    client: SomaClient,
    soma_user_id: str,
    force_refresh: bool = False,
) -> HistoryResponse:
    result = application_service.get_history(
        db, client, session_id, soma_user_id, force_refresh=force_refresh
    )
    return HistoryResponse(
        items=[
            HistoryItem(
                apply_sn=row.apply_sn,
                qustnr_sn=row.qustnr_sn,
                category=row.category,
                title=row.title,
                target_url=row.target_url,
                author=row.author,
                session_date_text=row.session_date_text,
                applied_at_text=row.applied_at_text,
                application_status=row.application_status,
                approval_status=row.approval_status,
            )
            for row in result.items
        ],
        cached_at=result.cached_at.isoformat(),
        refreshed=result.refreshed,
    )
