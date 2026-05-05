"""인증 엔드포인트. SPEC §1.3.

- POST /auth/login: ID/PW를 sidecar로 위임. session_id + 사용자 정보 반환.
- DELETE /auth/session: 현재 세션 폐기 (sidecar에 위임).
- GET /auth/whoami: 현재 세션 사용자 정보.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel, Field

from app.adapters.opensoma_client import OpenSomaClientError
from app.api.deps import DbSession, SessionId, SomaClient, session_expired_exc
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


def _map_sidecar_error(err: OpenSomaClientError) -> HTTPException:
    # sidecar의 401은 사용자에게 그대로 전파.
    if err.status == 401:
        if err.code == "SESSION_EXPIRED":
            return session_expired_exc()
        return HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": err.code, "message": err.message},
        )
    if err.status == 422:
        return HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": err.code, "message": err.message},
        )
    # 외 사이드카/홈페이지 장애는 503으로 추상화 (내부 에러 문구 노출 안 함).
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={"code": "UPSTREAM_UNAVAILABLE", "message": "OpenSoma is temporarily unavailable"},
    )


@router.post("/login", response_model=LoginResponse)
def login(body: LoginRequest, db: DbSession, client: SomaClient) -> LoginResponse:
    try:
        result = auth_service.login(db, client, body.username, body.password)
    except OpenSomaClientError as err:
        log.warning(
            "auth.login_failed",
            code=err.code,
            status=err.status,
            user_hint=body.username[:3] + "***",
        )
        raise _map_sidecar_error(err) from err
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
    try:
        client.logout(session_id)
    except OpenSomaClientError as err:
        # 로그아웃 실패는 부드럽게 — 어차피 클라이언트가 핸들 폐기하면 끝.
        log.info("auth.logout_upstream_error", code=err.code, status=err.status)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/whoami", response_model=WhoamiResponse)
def whoami(session_id: SessionId, db: DbSession, client: SomaClient) -> WhoamiResponse:
    try:
        result = client.whoami(session_id)
    except OpenSomaClientError as err:
        raise _map_sidecar_error(err) from err

    # whoami가 호출될 때마다 user_no 기준으로 갱신 (이름·role 변경 흡수).
    auth_service.upsert_user_from_whoami(db, result)

    return WhoamiResponse(
        soma_user_id=result.soma_user_id,
        user_no=result.user_no,
        user_name=result.user_name,
        role=result.role,
    )
