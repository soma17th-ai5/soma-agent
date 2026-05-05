"""Webex REST API 어댑터. SPEC §7.4.

설계 메모:
- sync httpx 기반. 동기화 잡은 APScheduler에서 1시간에 한 번 도는 백그라운드
  작업이라 async 의 이득이 작고, services 레이어가 SQLAlchemy 동기 Session 을
  쓰기 때문에 async/sync 경계 줄이는 편이 단순.
- pagination: Webex 는 RFC5988 `Link: <...>; rel="next"` 헤더로 cursor 제공.
  next URL에는 이미 cursor가 박혀있어, 그대로 GET 하면 된다.
- 429 응답: `Retry-After` 헤더에 명시된 초만큼 대기 후 재시도.
  네트워크 일시 오류(httpx.HTTPError) 도 tenacity로 지수 backoff.
- Authorization 토큰은 settings에서 한 번 읽고 헤더로 주입. 토큰값을
  로그 / 예외 메시지에 노출하지 않는다.
"""
from __future__ import annotations

import re
import time
from collections.abc import Iterator
from typing import Any

import httpx
import structlog
from tenacity import (
    RetryCallState,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = structlog.get_logger(__name__)

# Webex 공식 베이스. 변경되는 일은 거의 없으나 settings 로 분리하지 않은 이유는
# 다른 endpoint(예: 멘토링) 와 무관하게 Webex 전용이기 때문.
WEBEX_API_BASE = "https://webexapis.com/v1"

# `Link: <https://...?cursor=abc>; rel="next"` 형태에서 URL만 추출.
_LINK_RE = re.compile(r"<([^>]+)>\s*;\s*rel=\"?next\"?", re.IGNORECASE)


class WebexAuthError(Exception):
    """401/403 — 토큰 만료 또는 권한 부족."""


class WebexAPIError(Exception):
    """5xx 또는 그 외 비복구 가능 에러."""


class WebexClient:
    """Webex API HTTP 어댑터.

    httpx.Client 를 주입 받아 테스트에서 MockTransport 로 교체할 수 있게 했다.
    """

    def __init__(
        self,
        token: str,
        base_url: str = WEBEX_API_BASE,
        client: httpx.Client | None = None,
        timeout: float = 30.0,
        max_retry_after: float = 60.0,
    ) -> None:
        if not token:
            raise ValueError("Webex token is required")
        self._token = token
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        # `Retry-After` 가 비정상적으로 큰 값일 때(공격적 backoff) 잡을 막는 가드.
        self._max_retry_after = max_retry_after
        self._client = client or httpx.Client(timeout=timeout)

    # ------------------------------------------------------------------ utility

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> WebexClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/json",
        }

    # ---------------------------------------------------------------- requests

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        retry=retry_if_exception_type((httpx.HTTPError,)),
        reraise=True,
    )
    def _request(
        self, method: str, url: str, params: dict[str, Any] | None = None
    ) -> httpx.Response:
        """단발 요청 + 429 재시도. 401/403 은 즉시 WebexAuthError."""
        # url 이 절대 URL(다음 페이지) 또는 path 둘 다 허용.
        if not url.startswith("http"):
            url = f"{self._base_url}{url}"

        response = self._client.request(
            method, url, headers=self._headers(), params=params
        )

        # 429 — Retry-After 헤더 기반 1회 추가 대기. tenacity backoff 와 별개.
        if response.status_code == 429:
            retry_after = self._parse_retry_after(response.headers.get("Retry-After"))
            logger.warning(
                "webex.rate_limited",
                url=_redact(url),
                retry_after=retry_after,
            )
            time.sleep(retry_after)
            response = self._client.request(
                method, url, headers=self._headers(), params=params
            )

        if response.status_code in (401, 403):
            # 토큰 만료/권한 부족. 잡 ERROR 처리에 맡긴다.
            raise WebexAuthError(
                f"Webex auth failed ({response.status_code}) for {_redact(url)}"
            )

        if response.status_code >= 500:
            raise WebexAPIError(
                f"Webex {response.status_code} for {_redact(url)}"
            )

        if response.status_code >= 400:
            # 400 등은 재시도 의미 없음 — 즉시 실패.
            raise WebexAPIError(
                f"Webex {response.status_code} for {_redact(url)}: "
                f"{response.text[:200]}"
            )

        return response

    def _parse_retry_after(self, header_value: str | None) -> float:
        if not header_value:
            return 1.0
        try:
            seconds = float(header_value)
        except ValueError:
            return 1.0
        return max(0.0, min(seconds, self._max_retry_after))

    # ----------------------------------------------------------------- public

    def list_rooms(self, room_type: str = "group", max_per_page: int = 100) -> Iterator[dict[str, Any]]:
        """`GET /rooms?type={room_type}` 페이지네이션 순회.

        SPEC §7.4 에 따라 MVP 는 `group` 만 수집. yields full payload.
        """
        params: dict[str, Any] = {"type": room_type, "max": max_per_page}
        yield from self._paginate("/rooms", params)

    def list_messages(
        self,
        room_id: str,
        before: str | None = None,
        before_message: str | None = None,
        max_per_page: int = 100,
    ) -> Iterator[dict[str, Any]]:
        """`GET /messages?roomId=...` 페이지네이션 순회 (desc: 최신→과거).

        Args:
            room_id: Webex room id.
            before: ISO8601 datetime — 이 시각 이전 메시지만.
            before_message: 메시지 id — 이 메시지보다 더 과거의 메시지만.
            max_per_page: 페이지당 메시지 수 (Webex 상한 1000, 안전한 100 기본).
        """
        params: dict[str, Any] = {"roomId": room_id, "max": max_per_page}
        if before:
            params["before"] = before
        if before_message:
            params["beforeMessage"] = before_message
        yield from self._paginate("/messages", params)

    def get_person(self, person_id: str) -> dict[str, Any]:
        """`GET /people/{id}` — 봇 식별 등 보조 용도."""
        response = self._request("GET", f"/people/{person_id}")
        return response.json()

    # --------------------------------------------------------------- internal

    def _paginate(self, path: str, params: dict[str, Any]) -> Iterator[dict[str, Any]]:
        """Webex Link 헤더 cursor 페이지네이션 internal helper.

        첫 요청은 path+params 로, 이후 요청은 next URL 그대로 (params=None).
        """
        next_url: str | None = path
        next_params: dict[str, Any] | None = params
        while next_url:
            response = self._request("GET", next_url, params=next_params)
            payload = response.json()
            items: list[dict[str, Any]] = payload.get("items", [])
            yield from items

            link_header = response.headers.get("Link")
            next_url = _parse_next_link(link_header)
            # 다음 페이지에는 cursor 가 URL 에 박혀 오므로 params는 비운다.
            next_params = None


def _parse_next_link(link_header: str | None) -> str | None:
    """RFC5988 Link 헤더에서 `rel="next"` URL 추출. 없으면 None."""
    if not link_header:
        return None
    match = _LINK_RE.search(link_header)
    if not match:
        return None
    return match.group(1)


def _redact(url: str) -> str:
    """로그용 URL — 쿼리스트링 제거(혹시 모를 토큰/이메일 노출 방지)."""
    return url.split("?", 1)[0]


def _log_retry(retry_state: RetryCallState) -> None:  # pragma: no cover
    logger.info(
        "webex.retry",
        attempt=retry_state.attempt_number,
        wait=getattr(retry_state.next_action, "sleep", None),
    )
