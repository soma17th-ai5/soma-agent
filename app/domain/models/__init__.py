"""SQLAlchemy ORM 모델. 모든 모델은 동일한 `Base` 메타데이터를 공유한다.

Alembic env.py 는 여기서 `Base.metadata` 를 import 해서 마이그레이션 자동 생성에 사용한다.
도메인 모듈을 추가할 때 이 파일에서도 import 해 메타데이터에 등록되게 한다.
"""
from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """모든 ORM 모델의 베이스."""


# 도메인 모듈 등록 (메타데이터 수집을 위해 import 필요).
from app.domain.models.application import Application  # noqa: E402
from app.domain.models.mentoring import Mentoring, MentoringApplicant  # noqa: E402
from app.domain.models.notice import Notice  # noqa: E402
from app.domain.models.notice_attachment import NoticeAttachment  # noqa: E402
from app.domain.models.sync_state import SyncState  # noqa: E402
from app.domain.models.user import User  # noqa: E402
from app.domain.models.webex import WebexMessage, WebexRoom  # noqa: E402

__all__ = [
    "Application",
    "Base",
    "Mentoring",
    "MentoringApplicant",
    "Notice",
    "NoticeAttachment",
    "SyncState",
    "User",
    "WebexMessage",
    "WebexRoom",
]
