"""Upstage Solar chat completions + function-calling 어댑터.

Upstage API는 OpenAI Chat Completions 스펙 호환이므로 동일 페이로드(messages, tools,
tool_choice) 그대로 사용한다. SDK 미사용 — 의존성 최소화 위해 httpx 직호출.

router 노드는 본 클라이언트의 `chat()`을 통해 함수 호출 형식의 plan(`tool_calls[]`)을
받아 SPEC §5.2 tool_plan(≤2)으로 변환한다. 본 모듈은 *원시 응답을 정규화*하기만
하고, 도메인 결정(plan 절단·검증)은 router 노드에서 수행한다.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.config import get_settings

SOLAR_CHAT_URL = "https://api.upstage.ai/v1/chat/completions"


class SolarChatError(Exception):
    """Solar chat API 실패. 사용자에게 노출하지 않고 호출자가 ToolResult로 변환."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(f"[{status}] {message}")
        self.status = status
        self.message = message


@dataclass(frozen=True)
class ChatToolCall:
    """단일 함수 호출 제안 — Solar/OpenAI 응답의 tool_calls[i] 정규화."""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class ChatResponse:
    """chat() 결과를 router가 다루기 쉬운 형태로 정규화.

    - content: 자유 텍스트 응답. tool_calls가 있으면 보통 None 또는 빈 문자열.
    - tool_calls: function-calling 결과. 비어 있으면 plan 없음 (직접 답변 의도).
    - finish_reason: "stop" | "tool_calls" | "length" | ...
    """

    content: str | None
    tool_calls: list[ChatToolCall] = field(default_factory=list)
    finish_reason: str = "stop"


class SolarChatClient:
    """Upstage Solar chat completions 클라이언트.

    함수 호출:
      tools=[{"type": "function", "function": {"name", "description", "parameters": {...}}}]
      tool_choice="auto" | "none" | {"type":"function", "function":{"name": ...}}
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        timeout_s: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        settings = get_settings()
        self._api_key = api_key if api_key is not None else settings.solar_api_key
        self._model = model or settings.solar_llm_model
        self._http = httpx.Client(timeout=timeout_s, transport=transport)

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> SolarChatClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    # --- Public API -----------------------------------------------------

    def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        temperature: float = 0.0,
    ) -> ChatResponse:
        """Solar chat 호출.

        - messages: OpenAI 포맷 ({"role": "system|user|assistant|tool", "content": ...}).
        - tools: function 카탈로그. 없으면 일반 chat.
        - tool_choice: 강제/제한 옵션. None이면 모델 자율("auto" 동등).
        - temperature: 기본 0 — router 결정성 우선.
        """
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "temperature": temperature,
        }
        if tools:
            payload["tools"] = tools
        if tool_choice is not None:
            payload["tool_choice"] = tool_choice

        try:
            resp = self._http.post(
                SOLAR_CHAT_URL,
                json=payload,
                headers={"Authorization": f"Bearer {self._api_key}"},
            )
        except httpx.HTTPError as e:
            raise SolarChatError(0, f"network error: {e}") from e

        if not resp.is_success:
            raise SolarChatError(resp.status_code, _extract_error_message(resp))

        return _parse_response(resp.json())


def _parse_response(body: dict[str, Any]) -> ChatResponse:
    choices = body.get("choices") or []
    if not choices:
        raise SolarChatError(500, "empty choices in chat response")

    choice = choices[0]
    message = choice.get("message") or {}
    finish_reason = str(choice.get("finish_reason") or "stop")

    raw_tool_calls = message.get("tool_calls") or []
    tool_calls: list[ChatToolCall] = []
    for tc in raw_tool_calls:
        fn = tc.get("function") or {}
        name = fn.get("name")
        if not name:
            # 이름 없는 tool_call은 무효 — 무시 (router가 실패 처리).
            continue
        args_raw = fn.get("arguments") or "{}"
        try:
            args = json.loads(args_raw) if isinstance(args_raw, str) else dict(args_raw)
        except json.JSONDecodeError:
            # 잘못된 JSON arguments는 빈 dict로 전달, 검증은 router 책임.
            args = {}
        tool_calls.append(
            ChatToolCall(id=str(tc.get("id") or ""), name=str(name), arguments=args)
        )

    content_raw = message.get("content")
    content = str(content_raw) if isinstance(content_raw, str) and content_raw else None
    return ChatResponse(content=content, tool_calls=tool_calls, finish_reason=finish_reason)


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
