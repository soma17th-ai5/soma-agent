"""인증 관련 DTO. sidecar(opensoma_client) ↔ service ↔ router 사이를 흐른다."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class LoginDTO:
    """sidecar `login` 결과. session_id 포함."""

    session_id: str
    soma_user_id: str
    user_no: str
    user_name: str | None
    role: str


@dataclass(slots=True, frozen=True)
class WhoamiDTO:
    """sidecar `whoami` 결과. session_id 없음 (요청에 동봉)."""

    soma_user_id: str
    user_no: str
    user_name: str | None
    role: str
