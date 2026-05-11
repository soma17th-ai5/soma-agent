"""인증 엔드포인트. SPEC §1.3.

- POST /auth/login: ID/PW를 sidecar로 위임. session_id + 사용자 정보 반환.
- DELETE /auth/session: 현재 세션 폐기 (sidecar에 위임).
- GET /auth/whoami: 현재 세션 사용자 정보.

도메인/업스트림 예외는 raise만 하면 app-level 핸들러가 표준 응답으로 변환한다.
"""
from __future__ import annotations

from fastapi import APIRouter, Response, status
from pydantic import BaseModel, Field

from app.api.deps import DbSession, SessionId, SomaClient
from app.observability.logging import get_logger
from app.services import auth as auth_service

router = APIRouter(prefix="/auth", tags=["auth"])
log = get_logger("app.api.auth")


class LoginRequest(BaseModel):
    username: str = Field(min_length=1)
    password: str = Field(min_length=1)


class LoginResponse(BaseModel):
    session_id: str
    soma_user_id: str
    user_no: str
    user_name: str | None
    role: str


class WhoamiResponse(BaseModel):
    soma_user_id: str
    user_no: str
    user_name: str | None
    role: str


@router.post("/login", response_model=LoginResponse)
def login(body: LoginRequest, db: DbSession, client: SomaClient) -> LoginResponse:
    result = auth_service.login(db, client, body.username, body.password)
    log.info("auth.login_ok", user_no_prefix=result.user_no[:8])
    return LoginResponse(
        session_id=result.session_id,
        soma_user_id=result.soma_user_id,
        user_no=result.user_no,
        user_name=result.user_name,
        role=result.role,
    )


@router.delete("/session", status_code=status.HTTP_204_NO_CONTENT)
def logout(session_id: SessionId, client: SomaClient) -> Response:
    auth_service.logout(client, session_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/whoami", response_model=WhoamiResponse)
def whoami(session_id: SessionId, db: DbSession, client: SomaClient) -> WhoamiResponse:
    result = client.whoami(session_id)
    # whoami가 호출될 때마다 user_no 기준으로 갱신 (이름·role 변경 흡수).
    auth_service.upsert_user_from_whoami(db, result)
    return WhoamiResponse(
        soma_user_id=result.soma_user_id,
        user_no=result.user_no,
        user_name=result.user_name,
        role=result.role,
    )
