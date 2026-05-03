import asyncio
import json
from soma_app.agents.orchestrator import soma_orchestrator
from soma_app.models.schemas.soma import SomaChatRequest

async def run_test_scenario(scenario_name: str, query: str):
    print(f"\n{'='*20} {scenario_name} {'='*20}")
    print(f"사용자 질문: {query}")
    
    # 프론트엔드 스키마에 맞춘 요청 객체 생성
    request = SomaChatRequest(message=query)
    response = await soma_orchestrator.process_query(query=request.message)
    
    print(f"에이전트 답변:\n{response.answer}")
    
    print("\n[출처 정보]")
    for src in response.sources:
        print(f"- 제목: {src.title}")
        if src.date: print(f"  날짜: {src.date}")
        if src.url: print(f"  URL: {src.url}")
        if src.mentoringId: print(f"  멘토링ID: {src.mentoringId}")
        if src.time: print(f"  시간: {src.time}")

    print("\n[제안된 액션]")
    for action in response.suggestedActions:
        print(f"- 액션: {action.actionType}")
        print(f"  라벨: {action.label}")
        print(f"  페이로드: {action.payload}")
    print(f"{'='*60}\n")

async def main():
    # 5대 핵심 시나리오 테스트
    test_cases = [
        ("시나리오 1: 공지사항 확인", "이번 주에 내가 놓치면 안 되는 공지 알려줘."),
        ("시나리오 2: 멘토링 검색", "백엔드나 시스템 설계 관련 멘토링 찾아줘."),
        ("시나리오 3: 접수 내역 확인", "내가 신청한 멘토링 보여줘."),
        ("시나리오 4: 멘토링 신청", "1번 멘토링 신청하고 싶은데 방법 알려줘."),
        ("시나리오 5: Webex 정보 요약", "최근 Webex에서 부산 오프라인 행사 얘기 나온 거 정리해줘.")
    ]

    for name, query in test_cases:
        await run_test_scenario(name, query)

if __name__ == "__main__":
    asyncio.run(main())
