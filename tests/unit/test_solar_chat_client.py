"""SolarChatClient 정규화 동작 검증 — httpx.MockTransport로 응답 주입."""
from __future__ import annotations

import json

import httpx
import pytest

from app.adapters.solar_chat_client import (
    ChatToolCall,
    SolarChatClient,
    SolarChatError,
)


def _client(handler):  # type: ignore[no-untyped-def]
    return SolarChatClient(
        api_key="test", model="solar-pro", transport=httpx.MockTransport(handler)
    )


def test_should_parsePlainContent_when_noToolCalls() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["model"] == "solar-pro"
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "안녕하세요"},
                        "finish_reason": "stop",
                    }
                ]
            },
        )

    with _client(handler) as c:
        resp = c.chat([{"role": "user", "content": "hi"}])

    assert resp.content == "안녕하세요"
    assert resp.tool_calls == []
    assert resp.finish_reason == "stop"


def test_should_parseToolCalls_when_modelInvokesFunction() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call-1",
                                    "type": "function",
                                    "function": {
                                        "name": "knowledge.search",
                                        "arguments": json.dumps(
                                            {"query": "백엔드", "k": 5}
                                        ),
                                    },
                                }
                            ],
                        },
                        "finish_reason": "tool_calls",
                    }
                ]
            },
        )

    with _client(handler) as c:
        resp = c.chat(
            [{"role": "user", "content": "백엔드 멘토링"}],
            tools=[{"type": "function", "function": {"name": "knowledge.search"}}],
            tool_choice="auto",
        )

    assert resp.content is None
    assert resp.finish_reason == "tool_calls"
    assert resp.tool_calls == [
        ChatToolCall(id="call-1", name="knowledge.search", arguments={"query": "백엔드", "k": 5})
    ]


def test_should_normalizeBadJsonArguments_to_emptyDict() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "tool_calls": [
                                {
                                    "id": "call-2",
                                    "function": {
                                        "name": "x.y",
                                        "arguments": "{not valid json",
                                    },
                                }
                            ],
                        },
                        "finish_reason": "tool_calls",
                    }
                ]
            },
        )

    with _client(handler) as c:
        resp = c.chat([{"role": "user", "content": "x"}])

    assert len(resp.tool_calls) == 1
    assert resp.tool_calls[0].arguments == {}


def test_should_raiseSolarChatError_when_apiReturnsError() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429, json={"error": {"message": "Rate limit exceeded"}}
        )

    with _client(handler) as c, pytest.raises(SolarChatError) as exc:
        c.chat([{"role": "user", "content": "x"}])

    assert exc.value.status == 429
    assert "Rate limit" in exc.value.message


def test_should_raiseSolarChatError_when_emptyChoices() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": []})

    with _client(handler) as c, pytest.raises(SolarChatError):
        c.chat([{"role": "user", "content": "x"}])
