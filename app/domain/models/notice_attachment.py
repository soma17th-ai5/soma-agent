"""공지 첨부 ORM. SPEC §3.1 notice_attachments 매핑.

OpenSoma NoticeDetail.content HTML 안에 anchor로 들어있는 첨부 파일 1건당 1행.
PDF 텍스트 추출 결과(`extracted_text`)는 RAG 인덱싱과 동시에 채워진다.

마이그레이션 메모:
- 이 PR은 ORM 모델만 추가. notices 테이블이 아직 없는 상태에서 FK로 연결할 수 없어
  마이그레이션은 #10 (notices 도메인) 작업과 함께 추가한다.
- `notice_id`는 우리 PK가 아닌 OpenSoma의 notice 번호 (notices.notice_id)와 동일.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.models import Base


class NoticeAttachment(Base):
    __tablename__ = "notice_attachments"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    # FK는 마이그레이션에서 notices.notice_id 로 걸 예정 (#10 합류 시).
    notice_id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), nullable=False, index=True
    )
    file_name: Mapped[str] = mapped_column(String(500), nullable=False)
    file_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    file_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    extracted_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    extracted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
