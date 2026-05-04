"""헬스체크 엔드포인트와 trace_id 미들웨어 검증."""
import json

import pytest
from fastapi.testclient import TestClient

from app.observability.logging import configure_logging, get_logger
from app.observability.tracing import TRACE_ID_HEADER


def test_should_return_ok_when_healthz_called(client: TestClient) -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_should_include_trace_id_header_when_not_provided(client: TestClient) -> None:
    response = client.get("/healthz")
    assert TRACE_ID_HEADER in response.headers
    assert len(response.headers[TRACE_ID_HEADER]) > 0


def test_should_echo_trace_id_when_client_provides_one(client: TestClient) -> None:
    given_id = "test-trace-id-12345"
    response = client.get("/healthz", headers={TRACE_ID_HEADER: given_id})
    assert response.headers[TRACE_ID_HEADER] == given_id


def test_should_emit_json_log_when_logger_is_configured(
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_logging()
    get_logger("test").info("hello", key="value")
    captured = capsys.readouterr()
    log_line = captured.out.strip().splitlines()[-1]
    parsed = json.loads(log_line)
    assert parsed["event"] == "hello"
    assert parsed["key"] == "value"
    assert parsed["level"] == "info"
    assert "timestamp" in parsed
