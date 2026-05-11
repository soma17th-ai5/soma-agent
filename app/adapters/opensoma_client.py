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
    """sync httpx 클라이언트. 단일 httpx.Client 인스턴스를 재사용해
    connection pool 효율을 살린다. FastAPI 의존성 주입에서 요청별로 생성되지만
    인스턴스 안에서는 다중 호출(예: apply 후 history)이 같은 풀을 공유.

    base_url 미지정 시 settings.opensoma_sidecar_url 사용.
    """

    def __init__(self, base_url: str | None = None, timeout_s: float = 10.0) -> None:
        self._base_url = (base_url or get_settings().opensoma_sidecar_url).rstrip("/")
        self._http = httpx.Client(base_url=self._base_url, timeout=timeout_s)

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> OpenSomaClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    # --- 세션 -----------------------------------------------------------

    def login(self, username: str, password: str) -> LoginResult:
        resp = self._http.post("/sessions", json={"username": username, "password": password})
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
        resp = self._http.delete(f"/sessions/{session_id}")
        # 204 / 404 모두 OK (멱등성)
        if resp.status_code not in (204, 404):
            _raise_for_error(resp)

    def whoami(self, session_id: str) -> WhoamiResult:
        resp = self._http.get("/whoami", headers={"X-Soma-Session": session_id})
        _raise_for_error(resp)
        data = resp.json()
        return WhoamiResult(
            soma_user_id=data["soma_user_id"],
            user_no=data["user_no"],
            user_name=data.get("user_name"),
            role=data.get("role") or "TRAINEE",
        )

    # --- 공지 -----------------------------------------------------------

    def notice_list(self, session_id: str, page: int = 1) -> dict[str, Any]:
        """OpenSoma `NoticeListItem[]` + pagination을 그대로 통과시킴.

        반환 형태: {"items": [{id, title, author, createdAt}, ...], "pagination": {...}}
        """
        resp = self._http.get(
            "/notice",
            params={"page": page},
            headers={"X-Soma-Session": session_id},
        )
        _raise_for_error(resp)
        return resp.json()

    def notice_get(self, session_id: str, notice_id: int) -> dict[str, Any]:
        """`NoticeDetail` 을 그대로 반환: {id, title, author, createdAt, content}.

        첨부 파싱은 #13 services.notice_attachment 모듈 책임.
        """
        resp = self._http.get(
            f"/notice/{notice_id}",
            headers={"X-Soma-Session": session_id},
        )
        _raise_for_error(resp)
        return resp.json()

    # --- 멘토링 ---------------------------------------------------------

    def mentoring_list(
        self,
        session_id: str,
        *,
        status: str | None = None,
        type_: str | None = None,
        search: str | None = None,
        page: int = 1,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"page": page}
        if status is not None:
            params["status"] = status
        if type_ is not None:
            params["type"] = type_
        if search is not None:
            params["search"] = search
        resp = self._http.get(
            "/mentoring",
            params=params,
            headers={"X-Soma-Session": session_id},
        )
        _raise_for_error(resp)
        return resp.json()

    def mentoring_get(self, session_id: str, mentoring_id: int) -> dict[str, Any]:
        resp = self._http.get(
            f"/mentoring/{mentoring_id}",
            headers={"X-Soma-Session": session_id},
        )
        _raise_for_error(resp)
        return resp.json()

    def mentoring_apply(self, session_id: str, mentoring_id: int) -> dict[str, Any]:
        """sidecar가 신청 직후 history 를 조회해 apply_sn / qustnr_sn 매핑을 자동 해소.

        반환: {apply_sn, qustnr_sn, title, applied_at, application_status, approval_status}
        """
        resp = self._http.post(
            f"/mentoring/{mentoring_id}/apply",
            headers={"X-Soma-Session": session_id},
        )
        _raise_for_error(resp)
        return resp.json()

    def mentoring_cancel(self, session_id: str, apply_sn: int, qustnr_sn: int) -> None:
        resp = self._http.post(
            "/mentoring/cancel",
            json={"apply_sn": apply_sn, "qustnr_sn": qustnr_sn},
            headers={"X-Soma-Session": session_id},
        )
        if resp.status_code == 204:
            return
        _raise_for_error(resp)

    # --- 접수 내역 ------------------------------------------------------

    def application_history(self, session_id: str, page: int = 1) -> dict[str, Any]:
        resp = self._http.get(
            "/application/history",
            params={"page": page},
            headers={"X-Soma-Session": session_id},
        )
        _raise_for_error(resp)
        return resp.json()
