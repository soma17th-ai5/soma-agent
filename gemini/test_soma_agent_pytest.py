import pytest
import asyncio
from soma_app.agents.orchestrator import soma_orchestrator
from soma_app.models.schemas.soma import SomaChatRequest, SomaIntent

@pytest.mark.asyncio
async def test_notice_scenario():
    """시나리오 1: 공지사항 확인 테스트"""
    query = "이번 주에 내가 놓치면 안 되는 공지 알려줘."
    request = SomaChatRequest(message=query)
    response = await soma_orchestrator.process_query(query=request.message)
    
    assert response.answer is not None
    assert len(response.answer) > 0
    assert len(response.sources) > 0
    assert any("공지" in src.title or "안내" in src.title for src in response.sources)

@pytest.mark.asyncio
async def test_mentoring_search_scenario():
    """시나리오 2: 멘토링 검색 테스트"""
    query = "백엔드나 시스템 설계 관련 멘토링 찾아줘."
    request = SomaChatRequest(message=query)
    response = await soma_orchestrator.process_query(query=request.message)
    
    assert response.answer is not None
    # 데이터가 없을 수도 있으나 답변은 반드시 생성되어야 함
    assert len(response.answer) > 0

@pytest.mark.asyncio
async def test_my_status_scenario():
    """시나리오 3: 접수 내역 확인 테스트"""
    query = "내가 신청한 멘토링 보여줘."
    request = SomaChatRequest(message=query)
    response = await soma_orchestrator.process_query(query=request.message)
    
    assert response.answer is not None
    assert any("신청" in src.title for src in response.sources)

@pytest.mark.asyncio
async def test_mentoring_apply_scenario():
    """시나리오 4: 멘토링 신청 테스트"""
    query = "m1번 멘토링 신청하고 싶은데 방법 알려줘."
    request = SomaChatRequest(message=query)
    response = await soma_orchestrator.process_query(query=request.message)
    
    assert response.answer is not None
    assert len(response.sources) > 0
    assert "신청" in response.sources[0].title

@pytest.mark.asyncio
async def test_webex_summary_scenario():
    """시나리오 5: Webex 정보 요약 테스트"""
    query = "최근 Webex에서 부산 오프라인 행사 얘기 나온 거 정리해줘."
    request = SomaChatRequest(message=query)
    response = await soma_orchestrator.process_query(query=request.message)
    
    assert response.answer is not None
    assert any("Webex" in src.title for src in response.sources)

@pytest.mark.asyncio
async def test_mentoring_cancel_scenario():
    """신규 시나리오: 멘토링 취소 테스트 (구현 검증)"""
    query = "신청한 멘토링 취소하고 싶어."
    request = SomaChatRequest(message=query)
    response = await soma_orchestrator.process_query(query=request.message)
    
    assert response.answer is not None
    assert "취소" in response.answer or "관리" in response.sources[0].title

@pytest.mark.asyncio
async def test_unknown_intent_fallback():
    """Fallback 테스트: 알 수 없는 질문"""
    query = "오늘 날씨 어때?"
    request = SomaChatRequest(message=query)
    response = await soma_orchestrator.process_query(query=request.message)
    
    assert response.answer is not None
    # UNKNOWN 의도라도 답변은 생성되어야 함
    assert len(response.answer) > 0
