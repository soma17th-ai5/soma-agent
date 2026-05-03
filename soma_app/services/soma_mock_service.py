from datetime import datetime, timedelta
from typing import List
from soma_app.models.schemas.soma import (
    Notice, Mentoring, WebexMessage, 
    MentoringStatus, SomaActionResponse, SomaActionType
)

class SomaMockService:
    def __init__(self):
        # Mock Notices
        self.notices = [
            Notice(
                id="n1",
                title="[안내] 2026년 소마 중간평가 자료 제출 안내",
                content="중간평가 자료를 5월 8일까지 제출해주시기 바랍니다.",
                date="2026-05-01",
                is_important=True
            ),
            Notice(
                id="n2",
                title="[공지] 5월 멘토링 신청 기간 안내",
                content="5월 7일 마감되는 멘토링 목록을 확인하세요.",
                date="2026-04-30"
            ),
            Notice(
                id="n3",
                title="[공지] 출석/교육 일정 변경 안내",
                content="5월 1일부로 일부 교육 일정이 변경되었습니다.",
                date="2026-05-01"
            )
        ]

        # Mock Mentorings
        self.mentorings = [
            Mentoring(
                id="m1",
                title="대규모 트래픽 처리 설계 및 최적화",
                mentor_name="김멘토",
                category="백엔드",
                start_at=datetime(2026, 5, 6, 19, 0),
                status=MentoringStatus.AVAILABLE,
                description="대규모 트래픽 환경에서의 아키텍처를 배웁니다."
            ),
            Mentoring(
                id="m2",
                title="Spring Boot 성능 개선 실무",
                mentor_name="이멘토",
                category="백엔드",
                start_at=datetime(2026, 5, 8, 15, 0),
                status=MentoringStatus.AVAILABLE,
                description="실제 서비스에서 발생하는 성능 병목을 해결합니다."
            ),
            Mentoring(
                id="m3",
                title="창업 아이템 검증 및 BM 설계",
                mentor_name="박멘토",
                category="창업",
                start_at=datetime(2026, 5, 10, 13, 0),
                status=MentoringStatus.AVAILABLE
            )
        ]

        # Mock Webex Messages
        self.webex_messages = [
            WebexMessage(
                id="w1",
                room_name="부산 연수생 소통방",
                sender="홍길동",
                text="부산 오프라인 교류 행사 4월 30일에 진행하는 거 맞나요?",
                created_at=datetime(2026, 4, 28, 10, 0)
            ),
            WebexMessage(
                id="w2",
                room_name="부산 연수생 소통방",
                sender="운영진",
                text="네 맞습니다. 장소 후보와 일정 조율 중입니다.",
                created_at=datetime(2026, 4, 28, 11, 0)
            )
        ]

    # 5. [Mock Service] Orchestrator의 툴 호출 요청을 받아 실제 로직(조회/처리) 수행 후 결과 반환
    async def get_notices(self) -> List[Notice]:
        return self.notices

    # 5. [Mock Service] Orchestrator의 툴 호출 요청을 받아 실제 로직(조회/처리) 수행 후 결과 반환
    async def search_mentorings(self, query: str) -> List[Mentoring]:
        # Simple keyword search for mock
        return [m for m in self.mentorings if query.lower() in m.title.lower() or query.lower() in m.category.lower()]

    # 5. [Mock Service] Orchestrator의 툴 호출 요청을 받아 실제 로직(조회/처리) 수행 후 결과 반환
    async def apply_mentoring(self, mentoring_id: str) -> SomaActionResponse:
        for m in self.mentorings:
            if m.id == mentoring_id:
                if m.status == MentoringStatus.AVAILABLE:
                    m.status = MentoringStatus.APPLIED
                    return SomaActionResponse(
                        success=True,
                        action=SomaActionType.APPLY,
                        message=f"'{m.title}' 신청에 성공했습니다.",
                        data={"title": m.title, "time": m.start_at.isoformat()}
                    )
                return SomaActionResponse(success=False, action=SomaActionType.APPLY, message="이미 마감되었거나 신청된 멘토링입니다.")
        return SomaActionResponse(success=False, action=SomaActionType.APPLY, message="해당 멘토링을 찾을 수 없습니다.")

    # 5. [Mock Service] Orchestrator의 툴 호출 요청을 받아 실제 로직(조회/처리) 수행 후 결과 반환
    async def get_webex_messages(self, room_name: str = None) -> List[WebexMessage]:
        if room_name:
            return [msg for msg in self.webex_messages if msg.room_name == room_name]
        return self.webex_messages

    # 5. [Mock Service] Orchestrator의 툴 호출 요청을 받아 실제 로직(조회/처리) 수행 후 결과 반환
    async def get_applied_mentorings(self) -> List[Mentoring]:
        return [m for m in self.mentorings if m.status == MentoringStatus.APPLIED]

soma_mock_service = SomaMockService()
