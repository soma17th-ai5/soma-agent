"""멘토링 ORM. SPEC §3.1 mentorings, mentoring_applicants 매핑.

#8 PoC 실측 응답:
{
  "id": 10786,
  "title": "...",
  "type": "멘토 특강",                                          # 한글 자유문자열
  "registrationPeriod": {"start": "2026-04-27", "end": "2026-05-31"},
  "sessionDate": "2026-05-31",
  "sessionTime": {"start": "20:00", "end": "22:00"},
  "attendees": {"current": 20, "max": 20},
  "approved": true,
  "status": "마감",                                             # 한글 자유문자열
  "author": "...",
  "createdAt": "2026-04-26"                                     # notice와 다른 포맷 (대시)
}

객체 구조라 컬럼을 분할. type/status는 한글 자유문자열 → ENUM 강제 안 함, VARCHAR.
"""
from __future__ import annotations

from datetime import date, datetime, time

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    Time,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain.models import Base


class Mentoring(Base):
    __tablename__ = "mentorings"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    mentoring_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    mentoring_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    registration_start_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    registration_end_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    session_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    session_start_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    session_end_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    session_started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    attendees_current: Mapped[int | None] = mapped_column(Integer, nullable=True)
    attendees_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    approved: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    mentoring_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    author: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # mentoring 의 createdAt 은 "YYYY-MM-DD" 포맷
    created_at_text: Mapped[str | None] = mapped_column(String(50), nullable=True)
    content_html: Mapped[str | None] = mapped_column(Text, nullable=True)
    venue: Mapped[str | None] = mapped_column(String(500), nullable=True)
    detail_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    last_fetched_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    applicants: Mapped[list[MentoringApplicant]] = relationship(
        back_populates="mentoring",
        cascade="all, delete-orphan",
    )


class MentoringApplicant(Base):
    """멘토링 상세 응답의 applicants[] — 익명화(HMAC)된 이름만 저장."""

    __tablename__ = "mentoring_applicants"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    mentoring_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("mentorings.mentoring_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    applicant_name_hash: Mapped[str] = mapped_column(String(32), nullable=False)
    applied_at_text: Mapped[str | None] = mapped_column(String(50), nullable=True)
    cancelled_at_text: Mapped[str | None] = mapped_column(String(50), nullable=True)
    applicant_status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    collected_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    mentoring: Mapped[Mentoring] = relationship(back_populates="applicants")
