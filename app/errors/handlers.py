"""FastAPI 예외 핸들러. `app.main.create_app`에서 등록한다.

- `api_error_handler`: 도메인 예외(BaseAPIException 하위) → 표준 응답
- `opensoma_error_handler`: 어댑터 예외(`OpenSomaClientError`) → 표준 응답
- `validation_error_handler`: Pydantic `RequestValidationError` → flat 422

응답 포맷(.claude/rules/api.md):
    {"code": "...", "message": "...", "details": [...]}
"""
from __future__ import annotations

from typing import Any

from fastapi import Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.adapters.opensoma_client import OpenSomaClientError
from app.errors import codes
from app.errors.exceptions import BaseAPIException
from app.observability.logging import get_logger

log = get_logger("app.errors.handlers")


def _payload(
    code: str,
    message: str,
    details: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {"code": code, "message": message}
    if details:
        body["details"] = details
    return body


async def api_error_handler(_: Request, exc: Exception) -> JSONResponse:
    """모든 BaseAPIException 하위 예외 → 표준 응답."""
    assert isinstance(exc, BaseAPIException)  # FastAPI 타이핑 보정
    return JSONResponse(
        status_code=exc.status_code,
        content=_payload(exc.code, exc.message, exc.details),
        headers=exc.headers,
    )


async def opensoma_error_handler(_: Request, exc: Exception) -> JSONResponse:
    """OpenSomaClientError → 표준 응답.

    매핑 정책:
    - 401 SESSION_EXPIRED → 401 SESSION_EXPIRED + X-Soma-Session-Expired 헤더
    - 401 그 외          → 401 UPSTREAM_AUTH_FAILED (원본 code/message 보존)
    - 404                → 404 UPSTREAM_NOT_FOUND
    - 422                → 422 UPSTREAM_UNPROCESSABLE
    - 그 외              → 503 UPSTREAM_UNAVAILABLE (내부 정보 비노출)
    """
    assert isinstance(exc, OpenSomaClientError)

    if exc.status == 401 and exc.code == "SESSION_EXPIRED":
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content=_payload(
                codes.SESSION_EXPIRED,
                "OpenSoma session has expired. Please re-login.",
            ),
            headers={"X-Soma-Session-Expired": "true"},
        )
    if exc.status == 401:
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content=_payload(exc.code, exc.message),
        )
    if exc.status == 404:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content=_payload(exc.code or codes.UPSTREAM_NOT_FOUND, exc.message),
        )
    if exc.status == 422:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=_payload(exc.code or codes.UPSTREAM_UNPROCESSABLE, exc.message),
        )

    # 5xx/네트워크 에러: 내부 진단 정보를 그대로 클라이언트에 노출하지 않는다.
    # 디버깅을 위해 스택트레이스는 로그에 보존한다.
    log.warning(
        "opensoma.upstream_unavailable",
        upstream_status=exc.status,
        upstream_code=exc.code,
        exc_info=exc,
    )
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content=_payload(
            codes.UPSTREAM_UNAVAILABLE,
            "OpenSoma is temporarily unavailable",
        ),
    )


async def validation_error_handler(_: Request, exc: Exception) -> JSONResponse:
    """Pydantic RequestValidationError → flat 422.

    FastAPI 기본은 `{"detail": [...]}` 포맷이지만 프로젝트 규칙은 flat이므로 통일.
    필드별 사유는 `details` 배열로 매핑.
    """
    assert isinstance(exc, RequestValidationError)
    details = []
    for err in exc.errors():
        # `loc`는 ("body", "field_a", 0, "name") 같은 튜플. 첫 "body"는 제거하고 점-경로로 합친다.
        # 모두 "body" 뿐인(루트 레벨) 오류는 "__root__"로 표기해 클라이언트가 식별 가능하게.
        field_path = ".".join(str(p) for p in err.get("loc", []) if p != "body")
        details.append(
            {
                "field": field_path or "__root__",
                "reason": err.get("msg", ""),
            }
        )
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=_payload(codes.VALIDATION_FAILED, "Request validation failed", details),
    )
