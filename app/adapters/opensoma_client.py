"""OpenSoma sidecar HTTP RPC 클라이언트.

FastAPI 앱은 OpenSoma 홈페이지를 직접 호출하지 않고 이 어댑터를 통해
사이드카(`opensoma-sidecar`)의 좁은 HTTP 인터페이스(SPEC §3.3)만 호출한다.

본 모듈은 #9 (인증)에 필요한 메소드(login/logout/whoami)부터 제공.
notice/mentoring/application 메소드는 #10/#11/#13에서 점진적으로 추가.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from app.config import get_settings


class OpenSomaClientError(Exception):
    """OpenSoma sidecar 호출 실패. status·code·message를 포함한다."""

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(f"[{status}] {code}: {message}")
        self.status = status
        self.code = code
        self.message = message


@dataclass(frozen=True)
class LoginResult:
    session_id: str
    soma_user_id: str
    user_no: str
    user_name: str | None
    role: str


@dataclass(frozen=True)
class WhoamiResult:
    soma_user_id: str
    user_no: str
    user_name: str | None
    role: str


def _raise_for_error(resp: httpx.Response) -> None:
    if resp.is_success:
        return
    body = _safe_json(resp)
    code = body.get("code", "UPSTREAM_ERROR")
    message = body.get("message", resp.text or "")
    raise OpenSomaClientError(resp.status_code, code, message)


def _safe_json(resp: httpx.Response) -> dict[str, Any]:
    try:
        data = resp.json()
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


class OpenSomaClient:
    """sync httpx 클라이언트. FastAPI 동기 라우트와 동일 컨텍스트에서 사용.

    base_url 미지정 시 settings.opensoma_sidecar_url 사용.
    """

    def __init__(self, base_url: str | None = None, timeout_s: float = 10.0) -> None:
        self._base_url = (base_url or get_settings().opensoma_sidecar_url).rstrip("/")
        self._timeout = timeout_s

    def _client(self) -> httpx.Client:
        return httpx.Client(base_url=self._base_url, timeout=self._timeout)

    # --- 세션 -----------------------------------------------------------

    def login(self, username: str, password: str) -> LoginResult:
        with self._client() as c:
            resp = c.post("/sessions", json={"username": username, "password": password})
        _raise_for_error(resp)
        data = resp.json()
        return LoginResult(
            session_id=data["session_id"],
            soma_user_id=data["soma_user_id"],
            user_no=data["user_no"],
            user_name=data.get("user_name"),
            role=data.get("role") or "TRAINEE",
        )

    def logout(self, session_id: str) -> None:
        with self._client() as c:
            resp = c.delete(f"/sessions/{session_id}")
        # 204 / 404 모두 OK (멱등성)
        if resp.status_code not in (204, 404):
            _raise_for_error(resp)

    def whoami(self, session_id: str) -> WhoamiResult:
        with self._client() as c:
            resp = c.get("/whoami", headers={"X-Soma-Session": session_id})
        _raise_for_error(resp)
        data = resp.json()
        return WhoamiResult(
            soma_user_id=data["soma_user_id"],
            user_no=data["user_no"],
            user_name=data.get("user_name"),
            role=data.get("role") or "TRAINEE",
        )
