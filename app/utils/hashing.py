"""Webex 발신자/멘션 익명화 헬퍼.

SPEC §8.2 — Webex 응답에서 받은 person_id (또는 personEmail)는 즉시
HMAC-SHA256 으로 변환해 32-hex 문자열로 저장한다. 평문 person_id /
이메일은 DB·로그·Qdrant payload 어디에도 남기지 않는다.

salt는 환경변수(`WEBEX_SENDER_SALT`)에서 1회 로드해 캐시.
회전 시 모든 sender_key 재계산이 필요하므로 MVP 동안은 회전하지 않는다.
"""
from __future__ import annotations

import hashlib
import hmac
from functools import lru_cache

from app.config import get_settings

# HMAC-SHA256 hexdigest의 앞 32자만 사용 → CHAR(32) 컬럼과 정확히 매핑.
_KEY_LENGTH = 32


@lru_cache(maxsize=1)
def _get_salt() -> bytes:
    """`WEBEX_SENDER_SALT` 를 bytes로 캐시. 비어있으면 ValueError."""
    salt = get_settings().webex_sender_salt
    if not salt:
        # 익명화 키 없이 평문이 흘러들어가는 사고를 방지하기 위해
        # 명시적으로 실패시킨다.
        raise ValueError(
            "WEBEX_SENDER_SALT is not configured. Refusing to hash with empty salt."
        )
    return salt.encode("utf-8")


def anonymize_person_id(person_id: str) -> str:
    """Webex personId → 32자 hex 문자열.

    Args:
        person_id: Webex API 응답의 `personId` 또는 `mentionedPeople[*]`.

    Returns:
        HMAC-SHA256(salt, person_id) hexdigest 의 앞 32자.

    Raises:
        ValueError: WEBEX_SENDER_SALT 가 비어있거나 person_id 가 비어있을 때.
    """
    if not person_id:
        raise ValueError("person_id must not be empty")
    digest = hmac.new(_get_salt(), person_id.encode("utf-8"), hashlib.sha256).hexdigest()
    return digest[:_KEY_LENGTH]


def anonymize_many(person_ids: list[str] | None) -> list[str] | None:
    """선택적 리스트(예: mentionedPeople) 익명화. None은 그대로 None."""
    if not person_ids:
        return None
    return [anonymize_person_id(pid) for pid in person_ids]


def reset_salt_cache() -> None:
    """테스트에서 salt 변경 후 캐시 무효화용."""
    _get_salt.cache_clear()
