import json
from datetime import datetime
from typing import List, Dict, Any
from soma_app.models.schemas.soma import (
    SomaAgentResponse, SomaSourceType, SomaIntent, 
    SomaSource, SomaSuggestedAction, SomaActionType
)
from soma_app.services.soma_mock_service import soma_mock_service
from soma_app.services.service_factory import ServiceFactory
from soma_app.clients.open_ai import OpenAIClient
from soma_app.core.config import config
from soma_app.core.logger import logger
from soma_app.agents.prompts import INTENT_CLASSIFICATION_PROMPT, SOMA_AGENT_SYSTEM_PROMPT

class SomaOrchestrator:
    """
    Soma Agent의 의도를 분석하고 적절한 툴(Mock)을 호출하는 메인 컨트롤러
    """
    def __init__(self):
        self.solar_client = OpenAIClient(base_url="https://api.upstage.ai/v1/solar")
        self.embedding_service = ServiceFactory.get_embedding_service()

    async def classify_intent(self, query: str) -> Dict[str, Any]:
        """
        사용자 질문의 의도를 분석하여 사전에 정의된 Intent 중 하나로 매핑합니다.
        
        동작 방식:
        1. 사용자의 자연어 질의를 입력받아 LLM에게 JSON 형태의 의도(Intent)와 엔티티(Entity) 추출을 요청합니다.
        2. JSON 파싱 에러나 LLM API 호출 실패 등의 예외 발생 시, 시스템이 중단되지 않고
           안전하게 'UNKNOWN' 의도로 Fallback 처리하여 후속 로직에서 방어할 수 있도록 합니다.
        """
        try:
            prompt = INTENT_CLASSIFICATION_PROMPT.format(query=query)
            response_text = await self.solar_client.generate(
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"}
            )
            return json.loads(response_text)
        except json.JSONDecodeError as e:
            logger.error(f"Intent parsing failed: {e}, Response: {response_text}")
            return {"intent": SomaIntent.UNKNOWN.value, "entities": {}}
        except Exception as e:
            logger.error(f"Intent classification error: {e}")
            return {"intent": SomaIntent.UNKNOWN.value, "entities": {}}

    async def process_query(self, query: str) -> SomaAgentResponse:
        # 3. [Orchestrator] LLM을 활용한 사용자 질의 의도(Intent) 분류 및 엔티티 추출
        classification = await self.classify_intent(query)
        intent = classification.get("intent")
        entities = classification.get("entities", {})
        
        context_data = ""
        source_type = SomaSourceType.SYSTEM
        sources = []
        suggested_actions = []

        # 4. [Orchestrator] 분류된 의도에 매칭되는 Mock Tool(서비스) 호출 준비
        if intent == SomaIntent.NOTICE:
            # 4-1. [Tool Calling] 해당 의도에 맞는 Mock 서비스 함수 호출하여 Context 획득
            notices = await soma_mock_service.get_notices()
            mock_text = "공지사항 요약:\n" + "\n".join([f"- {n.date}: {n.title}" for n in notices])
            context_data = f"{mock_text}"
            source_type = SomaSourceType.OPEN_SOMA
            for n in notices:
                sources.append(SomaSource(title=n.title, date=n.date, url=n.url or "https://swmaestro.org/"))
            suggested_actions.append(SomaSuggestedAction(
                actionType=SomaActionType.CALENDAR_ADD,
                label="주요 일정 캘린더 등록",
                payload={"noticeId": notices[0].id}
            ))

        elif intent == SomaIntent.MENTORING_SEARCH:
            keyword = entities.get("keyword") or entities.get("category") or "백엔드"
            # 4-1. [Tool Calling] 해당 의도에 맞는 Mock 서비스 함수 호출하여 Context 획득
            mentorings = await soma_mock_service.search_mentorings(keyword)
            context_data = "추천 멘토링 목록:\n" + "\n".join([f"- [{m.id}] {m.title} ({m.mentor_name} 멘토, {m.start_at})" for m in mentorings])
            source_type = SomaSourceType.OPEN_SOMA
            for m in mentorings:
                sources.append(SomaSource(
                    title=m.title, 
                    mentoringId=m.id, 
                    date=m.start_at.strftime("%Y-%m-%d"),
                    time=m.start_at.strftime("%H:%M"),
                    url="https://swmaestro.org/"
                ))
            if mentorings:
                suggested_actions.append(SomaSuggestedAction(
                    actionType=SomaActionType.APPLY,
                    label=f"{mentorings[0].title} 신청하기",
                    payload={"mentoringId": mentorings[0].id}
                ))

        elif intent == SomaIntent.MENTORING_APPLY:
            mentoring_id = entities.get("keyword") or "m1"
            # 4-1. [Tool Calling] 해당 의도에 맞는 Mock 서비스 함수 호출하여 Context 획득
            result = await soma_mock_service.apply_mentoring(mentoring_id)
            context_data = f"멘토링 신청 결과: {result.message}"
            source_type = SomaSourceType.OPEN_SOMA
            sources.append(SomaSource(title="멘토링 신청 시스템", url="https://swmaestro.org/"))
            if result.success:
                suggested_actions.append(SomaSuggestedAction(
                    actionType=SomaActionType.CALENDAR_ADD,
                    label="신청한 멘토링 일정 등록",
                    payload={"mentoringId": mentoring_id}
                ))

        elif intent == SomaIntent.MY_STATUS:
            # 4-1. [Tool Calling] 해당 의도에 맞는 Mock 서비스 함수 호출하여 Context 획득
            applied = await soma_mock_service.get_applied_mentorings()
            if applied:
                context_data = "현재 신청된 멘토링 내역:\n" + "\n".join([f"- {m.title} ({m.mentor_name} 멘토)" for m in applied])
                for m in applied:
                    sources.append(SomaSource(title=m.title, mentoringId=m.id, date=m.start_at.strftime("%Y-%m-%d")))
            else:
                context_data = "현재 신청된 멘토링 내역이 없습니다."
            source_type = SomaSourceType.OPEN_SOMA
            sources.append(SomaSource(title="내 신청 정보", url="https://swmaestro.org/"))

        elif intent == SomaIntent.WEBEX_SUMMARY:
            # 4-1. [Tool Calling] 해당 의도에 맞는 Mock 서비스 함수 호출하여 Context 획득
            messages = await soma_mock_service.get_webex_messages()
            context_data = "Webex 대화 내용:\n" + "\n".join([f"[{m.sender}] {m.text}" for m in messages])
            source_type = SomaSourceType.WEBEX
            sources.append(SomaSource(title="Webex 부산 연수생 소통방", url="https://webex.com/"))

        # 6. [Orchestrator] 획득한 Context(툴 실행 결과)를 System Prompt에 주입하여 최종 자연어 답변(LLM) 생성
        system_prompt = SOMA_AGENT_SYSTEM_PROMPT.format(context=context_data)
        answer = await self.solar_client.generate(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": query}
            ]
        )

        return SomaAgentResponse(
            answer=answer,
            sources=sources,
            suggestedActions=suggested_actions,
            source_type=source_type
        )

soma_orchestrator = SomaOrchestrator()
