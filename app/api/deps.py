"""FastAPI 공용 의존성.

- get_db: DB 세션 주입
- get_opensoma_client: sidecar 클라이언트 주입
- get_session_id: X-Soma-Session 헤더 추출. 누락 시 SomaAuthRequired raise.

도메인 예외는 `app.errors`에 정의되어 있고, 핸들러가 표준 응답으로 변환한다 — 여기서
HTTPException을 직접 만들지 않는다.
"""
from __future__ import annotations

from collections.abc import Generator
from typing import Annotated

from fastapi import Depends, Header
from sqlalchemy.orm import Session

from app.adapters.opensoma_client import OpenSomaClient
from app.db.session import get_db as _get_db
from app.errors.exceptions import SomaAuthRequired


def get_db() -> Generator[Session, None, None]:
    yield from _get_db()


def get_opensoma_client() -> OpenSomaClient:
    return OpenSomaClient()


def get_session_id(x_soma_session: Annotated[str | None, Header()] = None) -> str:
    if not x_soma_session:
        raise SomaAuthRequired()
    return x_soma_session


SessionId = Annotated[str, Depends(get_session_id)]
DbSession = Annotated[Session, Depends(get_db)]
SomaClient = Annotated[OpenSomaClient, Depends(get_opensoma_client)]
