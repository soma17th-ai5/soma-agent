"""사용자 접수 내역 DTO. SPEC §3.1 applications 캐시 결과 + 행 표현."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True, frozen=True)
class ApplicationItemDTO:
    """Application ORM 행을 라우터 경계로 노출할 때 쓰는 값 객체."""

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


@dataclass(slots=True, frozen=True)
class HistoryDTO:
    """`application_service.get_history` 결과. 캐시 hit/miss 메타 포함."""

    items: list[ApplicationItemDTO]
    cached_at: datetime
    refreshed: bool
