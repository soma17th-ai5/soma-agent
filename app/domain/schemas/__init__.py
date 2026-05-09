"""HTTP 경계의 Request/Response 스키마.

원칙:
- Request: `pydantic.BaseModel` (요청 본문 검증 + `to_dto()`)
- Response: `pydantic.dataclasses.dataclass` (OpenAPI 자동 생성 유지 + `from_dto()`)
- 내부 DTO와 1:1로 매핑. 서비스/어댑터는 이 모듈을 import하지 않는다.

이 경계 너머로 ORM/DTO를 *직접* 노출하지 않는다.
"""
from app.domain.schemas.application import HistoryItemSchema, HistoryResp
from app.domain.schemas.auth import (
    LoginReq,
    LoginResp,
    WhoamiResp,
)
from app.domain.schemas.mentoring import ApplyReq, CancelReq

__all__ = [
    "ApplyReq",
    "CancelReq",
    "HistoryItemSchema",
    "HistoryResp",
    "LoginReq",
    "LoginResp",
    "WhoamiResp",
]
