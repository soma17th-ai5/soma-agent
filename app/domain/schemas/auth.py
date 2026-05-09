"""인증 엔드포인트 Request/Response 스키마.

Request: BaseModel (검증 우선)
Response: pydantic.dataclasses.dataclass — OpenAPI 스키마 자동 생성 유지하면서
         pydantic v2의 빠른 직렬화 활용.
"""
from __future__ import annotations

from pydantic import BaseModel, Field
from pydantic.dataclasses import dataclass

from app.domain.dtos.auth import LoginDTO, WhoamiDTO


class LoginReq(BaseModel):
    username: str = Field(min_length=1)
    password: str = Field(min_length=1)


@dataclass
class LoginResp:
    session_id: str
    soma_user_id: str
    user_no: str
    user_name: str | None
    role: str

    @classmethod
    def from_dto(cls, dto: LoginDTO) -> LoginResp:
        return cls(
            session_id=dto.session_id,
            soma_user_id=dto.soma_user_id,
            user_no=dto.user_no,
            user_name=dto.user_name,
            role=dto.role,
        )


@dataclass
class WhoamiResp:
    soma_user_id: str
    user_no: str
    user_name: str | None
    role: str

    @classmethod
    def from_dto(cls, dto: WhoamiDTO) -> WhoamiResp:
        return cls(
            soma_user_id=dto.soma_user_id,
            user_no=dto.user_no,
            user_name=dto.user_name,
            role=dto.role,
        )
