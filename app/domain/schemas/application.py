"""사용자 접수 내역 Response 스키마."""
from __future__ import annotations

from pydantic.dataclasses import dataclass

from app.domain.dtos.application import ApplicationItemDTO, HistoryDTO


@dataclass
class HistoryItemSchema:
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

    @classmethod
    def from_dto(cls, dto: ApplicationItemDTO) -> HistoryItemSchema:
        return cls(
            apply_sn=dto.apply_sn,
            qustnr_sn=dto.qustnr_sn,
            category=dto.category,
            title=dto.title,
            target_url=dto.target_url,
            author=dto.author,
            session_date_text=dto.session_date_text,
            applied_at_text=dto.applied_at_text,
            application_status=dto.application_status,
            approval_status=dto.approval_status,
        )


@dataclass
class HistoryResp:
    items: list[HistoryItemSchema]
    cached_at: str
    refreshed: bool

    @classmethod
    def from_dto(cls, dto: HistoryDTO) -> HistoryResp:
        return cls(
            items=[HistoryItemSchema.from_dto(item) for item in dto.items],
            cached_at=dto.cached_at.isoformat(),
            refreshed=dto.refreshed,
        )
