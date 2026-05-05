"""HMAC 익명화 헬퍼 단위 테스트."""
from __future__ import annotations

import re

import pytest

from app.config import get_settings
from app.utils import hashing


@pytest.fixture(autouse=True)
def _set_salt(monkeypatch: pytest.MonkeyPatch) -> None:
    """매 테스트마다 일정한 salt 주입."""
    monkeypatch.setenv("WEBEX_SENDER_SALT", "test-salt-v1")
    # pydantic-settings 캐시 + hashing 모듈 lru_cache 모두 무효화.
    get_settings.cache_clear()
    hashing.reset_salt_cache()


def test_should_returnDeterministicHex_when_samePersonId() -> None:
    a = hashing.anonymize_person_id("Y2lzY29zcGFyazovL3VzL1BFT1BMRS9hYmM=")
    b = hashing.anonymize_person_id("Y2lzY29zcGFyazovL3VzL1BFT1BMRS9hYmM=")
    assert a == b


def test_should_return32CharHex_when_anonymized() -> None:
    digest = hashing.anonymize_person_id("anyone")
    assert len(digest) == 32
    # 16진수 문자만.
    assert re.fullmatch(r"[0-9a-f]{32}", digest)


def test_should_returnDifferentHex_when_differentPersonIds() -> None:
    a = hashing.anonymize_person_id("alice@example.com")
    b = hashing.anonymize_person_id("bob@example.com")
    assert a != b


def test_should_raiseValueError_when_personIdEmpty() -> None:
    with pytest.raises(ValueError):
        hashing.anonymize_person_id("")


def test_should_raiseValueError_when_saltMissing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WEBEX_SENDER_SALT", "")
    get_settings.cache_clear()
    hashing.reset_salt_cache()
    with pytest.raises(ValueError):
        hashing.anonymize_person_id("anyone")


def test_should_returnNone_when_anonymizeManyEmpty() -> None:
    assert hashing.anonymize_many(None) is None
    assert hashing.anonymize_many([]) is None


def test_should_returnAllHashed_when_anonymizeManyValid() -> None:
    result = hashing.anonymize_many(["a", "b"])
    assert result is not None
    assert len(result) == 2
    assert all(len(h) == 32 for h in result)
    assert result[0] != result[1]
