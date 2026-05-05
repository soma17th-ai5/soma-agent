"""사용자별 접수 내역 ORM. SPEC §3.1 applications 매핑.

cancel 호출에 (apply_sn, qustnr_sn) 둘 다 필요 — sidecar의 apply 응답이 둘 다 반환하므로
동기화 시 함께 저장. 신청/취소 직후 해당 사용자 행은 즉시 무효화.

ApplicationHistoryItem (#8 PoC 실측):
- id (= apply_sn)
- url 에 ?qustnrSn=N 포함 (이를 파싱해 qustnr_sn 추출)
- category, title, author, sessionDate, appliedAt, applicationStatus, approvalStatus, ...
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.models import Base


class Application(Base):
    __tablename__ = "applications"
    __table_args__ = (UniqueConstraint("soma_user_id", "apply_sn", name="uq_user_apply_sn"),)

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    soma_user_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    apply_sn: Mapped[int] = mapped_column(BigInteger, nullable=False)
    qustnr_sn: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    target_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    author: Mapped[str | None] = mapped_column(String(200), nullable=True)
    session_date_text: Mapped[str | None] = mapped_column(String(100), nullable=True)
    applied_at_text: Mapped[str | None] = mapped_column(String(50), nullable=True)
    application_status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    approval_status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    application_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    cached_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
