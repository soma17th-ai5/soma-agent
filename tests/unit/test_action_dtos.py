"""ActionProposal/ActionResult DTO 직렬화 회귀 테스트.

이전: `pydantic.BaseModel` (alias `requiresConfirmation` 정의)
이후: `@dataclass(slots=True, frozen=True)`

pydantic v2의 BaseModel은 alias를 출력에 자동 적용하지 않으므로
(populate_by_name=True 는 입력 전용), 두 형태 모두 JSON 출력 키는
필드명(`requires_confirmation`) 그대로다. 이 테스트가 그 호환성을 못박는다.
"""
from __future__ import annotations

import json
from dataclasses import asdict

from app.domain.dtos.action import ActionProposal, ActionResult


def test_should_serializeFieldNameNotAlias_when_actionProposalDumped() -> None:
    """JSON 키는 `requires_confirmation` (snake_case 필드명) 그대로."""
    proposal = ActionProposal(
        type="opensoma.mentoring.apply",
        label="멘토링 신청",
        payload={"mentoring_id": 1},
    )
    body = json.dumps(asdict(proposal), ensure_ascii=False)
    assert "\"requires_confirmation\": true" in body
    assert "requiresConfirmation" not in body


def test_should_carryDefaults_when_actionProposalConstructed() -> None:
    p = ActionProposal(type="x", label="y", payload={})
    assert p.requires_confirmation is True


def test_should_haveStatusUnion_when_actionResultDumped() -> None:
    r = ActionResult(type="x", status="success", message="ok")
    body = json.loads(json.dumps(asdict(r)))
    assert body["status"] == "success"
    assert body["payload"] is None
