"""커스텀 도메인 예외. 모두 `BaseAPIException`을 상속.

각 예외는 `status_code`, `code`, `message`, `headers`, `details`를 메타로 갖고,
앱 레벨 핸들러(`handlers.api_error_handler`)가 이를 표준 응답 포맷으로 변환한다.

라우터/서비스는 try/except 없이 raise만 하면 된다 — HTTP 매핑은 핸들러 책임.
"""
from __future__ import annotations

from typing import Any, ClassVar

from app.errors import codes


# N818: BaseAPIException은 FastAPI/HTTPException 관례를 따르는 베이스 — Error 접미사 강제 안 함.
class BaseAPIException(Exception):  # noqa: N818
    """모든 도메인 예외의 베이스.

    `status_code`/`code`/`headers`는 클래스 메타로 두고 (ClassVar) 서브클래스가 override한다.
    `message`만 인스턴스 속성 — 같은 예외 종류라도 컨텍스트별 메시지를 달리 낼 수 있게.
    `details`는 인스턴스마다 가변이므로 `__init__`에서 받는다.
    """

    status_code: ClassVar[int] = 500
    code: ClassVar[str] = codes.INTERNAL_ERROR
    message: str = "Internal server error"
    headers: ClassVar[dict[str, str] | None] = None

    def __init__(
        self,
        message: str | None = None,
        *,
        details: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(message or self.message)
        if message is not None:
            self.message = message
        self.details = details


# ─── 인증/세션 ─────────────────────────────────────────────────────────────────


class SomaAuthRequired(BaseAPIException):
    """X-Soma-Session 헤더 누락."""

    status_code = 401
    code = codes.SOMA_AUTH_REQUIRED
    message = "X-Soma-Session header is required"


class SessionExpired(BaseAPIException):
    """OpenSoma 세션 만료. 클라이언트 재로그인 트리거용 헤더 동반."""

    status_code = 401
    code = codes.SESSION_EXPIRED
    message = "OpenSoma session has expired. Please re-login."
    headers: ClassVar[dict[str, str] | None] = {"X-Soma-Session-Expired": "true"}


class UpstreamAuthFailed(BaseAPIException):
    """업스트림(OpenSoma sidecar) 인증 실패. 401이지만 SESSION_EXPIRED는 아닌 경우.

    sidecar의 원본 code/message를 보존해서 클라이언트에 전달.
    """

    status_code = 401
    code = codes.UPSTREAM_AUTH_FAILED
    message = "Upstream authentication failed"


# ─── 입력 검증 ─────────────────────────────────────────────────────────────────


class InvalidRequest(BaseAPIException):
    """라우터/서비스에서 잡아낸 의미론적 입력 오류."""

    status_code = 422
    code = codes.INVALID_REQUEST
    message = "Invalid request"


# ─── 도메인 상태 ───────────────────────────────────────────────────────────────


class MentoringNotOpen(BaseAPIException):
    """멘토링이 신청 가능 상태가 아님."""

    status_code = 409
    code = codes.MENTORING_NOT_OPEN
    message = "Mentoring is not open for application"


# ─── 업스트림 ──────────────────────────────────────────────────────────────────


class UpstreamNotFound(BaseAPIException):
    """업스트림이 404 응답 (대상 리소스 없음)."""

    status_code = 404
    code = codes.UPSTREAM_NOT_FOUND
    message = "Upstream resource not found"


class UpstreamUnprocessable(BaseAPIException):
    """업스트림이 422 응답 (의미론적 입력 오류)."""

    status_code = 422
    code = codes.UPSTREAM_UNPROCESSABLE
    message = "Upstream rejected the request"


class UpstreamUnavailable(BaseAPIException):
    """업스트림 장애/네트워크 실패. 내부 진단 정보를 클라이언트로 노출하지 않는다."""

    status_code = 503
    code = codes.UPSTREAM_UNAVAILABLE
    message = "OpenSoma is temporarily unavailable"


# ─── 인프라 ────────────────────────────────────────────────────────────────────


class DatabaseUnavailable(BaseAPIException):
    """DB 연결/쿼리 실패. 내부 에러는 로그로만 남기고 일반화된 메시지를 응답."""

    status_code = 503
    code = codes.DATABASE_UNAVAILABLE
    message = "Database is unavailable"
