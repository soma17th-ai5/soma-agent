"""앱 전역 예외 체계 + FastAPI 핸들러.

라우터/서비스에서 try/except 없이 도메인 예외(BaseAPIException 하위)를 raise만 하면,
`app.main.create_app`이 등록한 핸들러가 표준 응답 포맷으로 변환한다.

응답 포맷(.claude/rules/api.md):
    {"code": "DOMAIN_ERROR_CODE", "message": "...", "details": [...]}
"""
from app.errors.codes import (
    DATABASE_UNAVAILABLE,
    INVALID_REQUEST,
    MENTORING_NOT_OPEN,
    SESSION_EXPIRED,
    SOMA_AUTH_REQUIRED,
    UPSTREAM_AUTH_FAILED,
    UPSTREAM_NOT_FOUND,
    UPSTREAM_UNAVAILABLE,
    UPSTREAM_UNPROCESSABLE,
    VALIDATION_FAILED,
)
from app.errors.exceptions import (
    BaseAPIException,
    DatabaseUnavailable,
    InvalidRequest,
    MentoringNotOpen,
    SessionExpired,
    SomaAuthRequired,
    UpstreamAuthFailed,
    UpstreamNotFound,
    UpstreamUnavailable,
    UpstreamUnprocessable,
)
from app.errors.handlers import (
    api_error_handler,
    opensoma_error_handler,
    validation_error_handler,
)

__all__ = [
    # codes
    "DATABASE_UNAVAILABLE",
    "INVALID_REQUEST",
    "MENTORING_NOT_OPEN",
    "SESSION_EXPIRED",
    "SOMA_AUTH_REQUIRED",
    "UPSTREAM_AUTH_FAILED",
    "UPSTREAM_NOT_FOUND",
    "UPSTREAM_UNAVAILABLE",
    "UPSTREAM_UNPROCESSABLE",
    "VALIDATION_FAILED",
    # exceptions
    "BaseAPIException",
    "DatabaseUnavailable",
    "InvalidRequest",
    "MentoringNotOpen",
    "SessionExpired",
    "SomaAuthRequired",
    "UpstreamAuthFailed",
    "UpstreamNotFound",
    "UpstreamUnavailable",
    "UpstreamUnprocessable",
    # handlers
    "api_error_handler",
    "opensoma_error_handler",
    "validation_error_handler",
]
