"""OpenSoma 어댑터 — notice/mentoring/application 메소드 검증 (httpx mock)."""
from __future__ import annotations

import httpx

from app.adapters.opensoma_client import OpenSomaClient


def make_client(handler) -> OpenSomaClient:  # type: ignore[no-untyped-def]
    transport = httpx.MockTransport(handler)
    client = OpenSomaClient(base_url="http://test")
    client._http.close()
    client._http = httpx.Client(transport=transport, base_url="http://test")
    return client


def test_should_passSession_when_calling_noticeList() -> None:
    captured: dict[str, str] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        captured["session"] = req.headers.get("X-Soma-Session", "")
        captured["path"] = req.url.path
        return httpx.Response(200, json={"items": [], "pagination": {"totalPages": 1}})

    client = make_client(handler)
    client.notice_list("sid-1", page=2)
    assert captured["session"] == "sid-1"
    assert captured["path"] == "/notice"


def test_should_returnDetail_when_noticeGetSucceeds() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": 1,
                "title": "t",
                "author": "a",
                "createdAt": "2026.04.07 15:14:20",
                "content": "<p>hi</p>",
            },
        )

    client = make_client(handler)
    detail = client.notice_get("sid", 1)
    assert detail["title"] == "t"
    assert detail["content"].startswith("<p>")


def test_should_filterParams_when_callingMentoringList() -> None:
    captured: dict[str, str] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        captured["query"] = str(req.url.query.decode())
        return httpx.Response(200, json={"items": [], "pagination": {}})

    client = make_client(handler)
    client.mentoring_list("sid", status="open", type_="public", search="백엔드", page=1)
    assert "status=open" in captured["query"]
    assert "type=public" in captured["query"]
    assert "search=" in captured["query"]


def test_should_returnApplyMapping_when_mentoringApplyCalled() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.method == "POST"
        assert req.url.path == "/mentoring/123/apply"
        return httpx.Response(
            200,
            json={
                "apply_sn": 999,
                "qustnr_sn": 123,
                "title": "t",
                "applied_at": "2026-05-05",
                "application_status": "접수완료",
                "approval_status": "-",
            },
        )

    client = make_client(handler)
    result = client.mentoring_apply("sid", 123)
    assert result["apply_sn"] == 999
    assert result["qustnr_sn"] == 123


def test_should_succeed_when_mentoringCancelReturns204() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.method == "POST"
        assert req.url.path == "/mentoring/cancel"
        return httpx.Response(204)

    client = make_client(handler)
    client.mentoring_cancel("sid", 999, 123)


def test_should_returnHistoryItems_when_applicationHistoryCalled() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": 58,
                        "url": "/sw/...?qustnrSn=11251&menuNo=200046",
                        "title": "...",
                    }
                ],
                "pagination": {"totalPages": 1},
            },
        )

    client = make_client(handler)
    payload = client.application_history("sid")
    assert payload["items"][0]["id"] == 58
    assert "qustnrSn=11251" in payload["items"][0]["url"]
