# Soma Agent `chat/message` 실행 흐름 (Execution Flow)

이 파일은 `chat/message` API 요청이 들어왔을 때부터 최종 응답이 반환될 때까지의 전체 실행 흐름을 추적하기 위한 TODO 체크리스트입니다. 각 파일의 주석 번호와 매칭됩니다.

## 🚀 실행 흐름 체크리스트

- [ ] **1. [Router]** 사용자 채팅 요청 수신 (API 엔드포인트)
    - 파일: `soma_app/routers/chat.py`
- [ ] **2. [Router]** Orchestrator로 질의(Query) 전달하여 비즈니스 로직 위임
    - 파일: `soma_app/routers/chat.py`
- [ ] **3. [Orchestrator]** LLM을 활용한 사용자 질의 의도(Intent) 분류 및 엔티티 추출
    - 파일: `soma_app/agents/orchestrator.py`
- [ ] **4. [Orchestrator]** 분류된 의도에 매칭되는 Mock Tool(서비스) 호출 준비
    - 파일: `soma_app/agents/orchestrator.py`
- [ ] **4-1. [Tool Calling]** 해당 의도에 맞는 Mock 서비스 함수 호출하여 Context 획득
    - 파일: `soma_app/agents/orchestrator.py`
- [ ] **5. [Mock Service]** Orchestrator의 툴 호출 요청을 받아 실제 로직(조회/처리) 수행 후 결과 반환
    - 파일: `soma_app/services/soma_mock_service.py`
- [ ] **6. [Orchestrator]** 획득한 Context(툴 실행 결과)를 System Prompt에 주입하여 최종 자연어 답변(LLM) 생성
    - 파일: `soma_app/agents/orchestrator.py`
- [ ] **7. [Router]** 최종 생성된 에이전트 응답(SomaAgentResponse) 반환
    - 파일: `soma_app/routers/chat.py`

---
*참고: 이 흐름은 `gemini/API.md` 사양을 준수하며 구현되었습니다.*
