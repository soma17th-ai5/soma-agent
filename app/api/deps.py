"""FastAPI 공용 의존성.

- get_db: DB 세션 주입
- get_opensoma_client: sidecar 클라이언트 주입
- get_session_id: X-Soma-Session 헤더 추출. 누락 시 401 SOMA_AUTH_REQUIRED.
- session_expired_exc: 401 SESSION_EXPIRED 응답 헬퍼 (X-Soma-Session-Expired 헤더 동반).
"""
from __future__ import annotations

from collections.abc import Generator
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.adapters.opensoma_client import OpenSomaClient
from app.db.session import get_db as _get_db


def get_db() -> Generator[Session, None, None]:
    yield from _get_db()


def get_opensoma_client() -> OpenSomaClient:
    return OpenSomaClient()


def get_session_id(x_soma_session: Annotated[str | None, Header()] = None) -> str:
    if not x_soma_session:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "SOMA_AUTH_REQUIRED",
                "message": "X-Soma-Session header is required",
            },
        )
    return x_soma_session


def session_expired_exc() -> HTTPException:
    """sidecar에서 401 SESSION_EXPIRED를 받았을 때 클라이언트로 전파."""
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={
            "code": "SESSION_EXPIRED",
            "message": "OpenSoma session has expired. Please re-login.",
        },
        headers={"X-Soma-Session-Expired": "true"},
    )


SessionId = Annotated[str, Depends(get_session_id)]
DbSession = Annotated[Session, Depends(get_db)]
SomaClient = Annotated[OpenSomaClient, Depends(get_opensoma_client)]
