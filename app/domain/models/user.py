"""사용자 ORM. SPEC §3.1 users 매핑.

OpenSoma whoami 응답: `{userId, userNm, userNo, userGb}`
- userId    : 로그인 username(=이메일). soma_user_id로 저장.
- userNo    : 32자 hex GUID. user_no.
- userNm    : 한글 이름.
- userGb    : 'C'(연수생)/'T'(멘토). role enum 매핑.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Enum, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.models import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    soma_user_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    user_no: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    user_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    role: Mapped[str] = mapped_column(
        Enum("TRAINEE", "MENTOR", "EXPERT", "OPERATOR", name="user_role"),
        nullable=False,
        default="TRAINEE",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )
