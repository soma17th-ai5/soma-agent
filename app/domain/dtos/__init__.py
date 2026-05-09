"""레이어 경계를 가로지르는 내부 데이터 전송 객체 (DTO).

원칙:
- 모두 `@dataclass(slots=True, frozen=True)` — 메모리 절감 + 불변성
- Pydantic `BaseModel`은 사용하지 않음 (외부 경계는 `app.domain.schemas` 책임)
- 외부 라이브러리 의존 없음 (qdrant-client, httpx 등 import 금지)

ORM 객체를 DTO로 변환하는 책임은 service 레이어에 둔다.
"""
from app.domain.dtos.action import ActionProposal, ActionResult
from app.domain.dtos.application import ApplicationItemDTO, HistoryDTO
from app.domain.dtos.auth import LoginDTO, WhoamiDTO
from app.domain.dtos.knowledge import KnowledgeSourceType, SearchHit

__all__ = [
    "ActionProposal",
    "ActionResult",
    "ApplicationItemDTO",
    "HistoryDTO",
    "KnowledgeSourceType",
    "LoginDTO",
    "SearchHit",
    "WhoamiDTO",
]
