"""공지 ORM. SPEC §3.1 notices 매핑.

OpenSoma 응답 형태(#8 PoC 실측):
- NoticeListItem: {id, title, author, createdAt}
- NoticeDetail: NoticeListItem + {content: HTML string}
- 별도 첨부 필드 없음 — content HTML anchor에서 추출(#13)
- createdAt 포맷: "YYYY.MM.DD HH:MM:SS" (점 구분, KST)
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.models import Base


class Notice(Base):
    __tablename__ = "notices"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    notice_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    author: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # 실측 포맷: "YYYY.MM.DD HH:MM:SS" (점 구분, KST 추정)
    created_at_text: Mapped[str | None] = mapped_column(String(50), nullable=True)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    content_html: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    detail_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    last_fetched_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
