"""Upstage Solar embedding 어댑터.

SPEC §3.2 — Qdrant 벡터 차원은 Solar embedding 결과와 일치해야 한다 (4096).
Upstage 임베딩 API는 "passage(저장용)"와 "query(검색용)" 모델이 분리되어 있고,
둘 모두 동일한 차원의 벡터를 반환하도록 설계되어 있어 같은 컬렉션에 저장·검색 가능.

본 모듈은 인덱서·검색 서비스가 의존하는 *얇은* 어댑터로, 외부 HTTP 호출과
인증 헤더 부착에만 책임을 진다. 청킹·점수 계산은 services 레이어에서 처리.
"""
from __future__ import annotations

from typing import Any

import httpx

from app.config import get_settings

# Upstage Embeddings API 엔드포인트. SDK 미사용 — 의존성 최소화 위해 httpx 직호출.
SOLAR_EMBEDDINGS_URL = "https://api.upstage.ai/v1/embeddings"


class SolarClientError(Exception):
    """Solar API 호출 실패. 사용자에게 노출하지 않고 상위에서 감싸 전달."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(f"[{status}] {message}")
        self.status = status
        self.message = message


class SolarClient:
    """Upstage Solar embedding API 동기 클라이언트.

    `httpx.Client`를 재사용해 connection pool 효율을 살린다. 테스트에서는
    생성자에 `transport`(`httpx.MockTransport`) 또는 사전 구성된 `client`를 주입.
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        passage_model: str | None = None,
        query_model: str | None = None,
        timeout_s: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        settings = get_settings()
        self._api_key = api_key if api_key is not None else settings.solar_api_key
        self._passage_model = passage_model or settings.solar_embedding_passage_model
        self._query_model = query_model or settings.solar_embedding_query_model
        # transport가 주어지면 base_url 없이 절대 URL로 호출.
        # 평문 운영 시에는 base_url 없이 SOLAR_EMBEDDINGS_URL 절대 경로로 POST.
        self._http = httpx.Client(timeout=timeout_s, transport=transport)

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> SolarClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    # --- Public API -----------------------------------------------------

    def embed_passages(self, texts: list[str]) -> list[list[float]]:
        """저장용(passage) 임베딩. 배치 호출.

        빈 리스트 입력 시 *API 호출 없이* 빈 리스트 반환 — 비용/레이턴시 절감.
        """
        if not texts:
            return []
        return self._embed(self._passage_model, texts)

    def embed_query(self, text: str) -> list[float]:
        """단일 검색 쿼리 임베딩. 항상 `query` 모델 사용."""
        vectors = self._embed(self._query_model, text)
        # 단일 입력 시 API는 길이 1 배열 반환.
        if not vectors:
            raise SolarClientError(500, "empty embedding response")
        return vectors[0]

    # --- Internal -------------------------------------------------------

    def _embed(self, model: str, inputs: str | list[str]) -> list[list[float]]:
        headers = {"Authorization": f"Bearer {self._api_key}"}
        payload: dict[str, Any] = {"model": model, "input": inputs}
        try:
            resp = self._http.post(SOLAR_EMBEDDINGS_URL, json=payload, headers=headers)
        except httpx.HTTPError as e:  # 네트워크/타임아웃 → 일관된 예외로 감쌈
            raise SolarClientError(0, f"network error: {e}") from e

        if not resp.is_success:
            message = _extract_error_message(resp)
            raise SolarClientError(resp.status_code, message)

        data = resp.json()
        items = data.get("data") or []
        # 응답 순서가 input 순서와 동일하도록 index로 정렬 (API 명세상 보장되지만 방어적).
        items_sorted = sorted(items, key=lambda x: x.get("index", 0))
        return [item["embedding"] for item in items_sorted]


def _extract_error_message(resp: httpx.Response) -> str:
    try:
        body = resp.json()
        if isinstance(body, dict):
            err = body.get("error")
            if isinstance(err, dict) and "message" in err:
                return str(err["message"])
            if "message" in body:
                return str(body["message"])
        return resp.text or "unknown error"
    except Exception:
        return resp.text or "unknown error"
