"""Calendar invite mock 어댑터. SPEC §4.2 calendar.invite.create.

운영 환경에서 외부 캘린더(Google/Microsoft) 연동이 추가되기 전까지 사용하는
결정론 가능 mock. `CALENDAR_MOCK_FAIL_RATE`(0.0~1.0) 비율로 `failed`를 반환해
프론트의 부분 실패(`data.calendarInvite.status = "failed"`) UX 검증을 가능하게 한다.

성공/실패 분기는 의사난수에 의존한다. 테스트는 `seed`를 직접 주입해 결정론적으로
동작하도록 하고, 실서비스에서는 `random.Random()`(엔트로피)로 동작한다.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime
from uuid import uuid4

from app.config import get_settings


@dataclass
class MockInviteResult:
    """캘린더 초대 mock 결과.

    status="failed"는 SPEC §6.4 부분 실패 시나리오(신청 성공 + 캘린더 실패)에서
    프론트가 표기할 사실 데이터로 그대로 ChatMessage에 흘러간다.
    """

    status: str  # "success" | "failed"
    invite_id: str | None
    title: str
    start_at: datetime
    end_at: datetime
    description: str | None
    location: str | None
    error: str | None = None


class CalendarMock:
    """캘린더 초대 mock 클라이언트.

    인스턴스는 stateless 하지 않다 — 내부 RNG 상태를 보유한다. 테스트에서는
    `seed` 인자로 결정론적 동작을 강제할 수 있다.
    """

    def __init__(self, *, fail_rate: float | None = None, seed: int | None = None) -> None:
        if fail_rate is None:
            fail_rate = get_settings().calendar_mock_fail_rate
        if not 0.0 <= fail_rate <= 1.0:
            raise ValueError(f"fail_rate must be in [0,1], got {fail_rate}")
        self._fail_rate = fail_rate
        self._rng = random.Random(seed)

    def create_invite(
        self,
        *,
        title: str,
        start_at: datetime,
        end_at: datetime,
        description: str | None = None,
        location: str | None = None,
    ) -> MockInviteResult:
        if end_at <= start_at:
            return MockInviteResult(
                status="failed",
                invite_id=None,
                title=title,
                start_at=start_at,
                end_at=end_at,
                description=description,
                location=location,
                error="end_at must be after start_at",
            )

        # fail_rate 비율로 의도적 실패 — 프론트 부분 실패 처리 검증용.
        if self._rng.random() < self._fail_rate:
            return MockInviteResult(
                status="failed",
                invite_id=None,
                title=title,
                start_at=start_at,
                end_at=end_at,
                description=description,
                location=location,
                error="mock_fail_injected",
            )

        return MockInviteResult(
            status="success",
            invite_id=f"mock-{uuid4().hex}",
            title=title,
            start_at=start_at,
            end_at=end_at,
            description=description,
            location=location,
        )
