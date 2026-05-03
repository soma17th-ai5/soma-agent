# PR 검증 지적 사항 체크리스트 (PR Feedback Checklist)

## 🚨 CRITICAL (치명적 결함)
- [x] **1. 자동화된 테스트 커버리지 확보 (`pytest` 도입)**
  - `gemini/test_soma_agent.py`를 `pytest` 형식으로 리팩토링 (또는 신규 테스트 파일 생성).
  - 단언문(`assert`)을 포함하여 자동화 환경에서 통과/실패가 명확히 판별되도록 구현.

## ⚠️ MINOR (개선 필요 사항)
- [x] **2. 에러 핸들링 및 정보 노출 방지 (`soma_app/clients/open_ai.py`)**
  - `OpenAIException`에서 원본 LLM 에러 메시지를 그대로 노출하지 않도록 가공.
- [x] **3. 미구현 인텐트 로직 추가 (`soma_app/agents/orchestrator.py`)**
  - `SomaIntent.MENTORING_CANCEL`에 대한 분기 처리 및 Mock 툴 호출 로직 추가.
- [x] **4. Pydantic 모델 Naming Convention 수정 (`soma_app/models/schemas/soma.py`)**
  - `camelCase` 필드명(`suggestedActions`, `chatSessionId` 등)을 `snake_case`로 변경하고, `Field(alias="...")` 적용.
- [x] **5. Orchestrator 최종 답변 실패 대비 Fallback 추가 (`soma_app/agents/orchestrator.py`)**
  - 답변 생성(`self.solar_client.generate`) 부분에 `try-except` 블록을 추가하여 서비스 장애 방지.
- [x] **6. 아키텍처 일관성 유지 (URL 하드코딩 제거)**
  - `SomaOrchestrator` 내 Upstage API URL 하드코딩 제거. `ServiceFactory`를 활용하여 주입.
- [x] **7. 타입 힌트 오류 교정**
  - `ServiceFactory.get_embedding_service`의 리턴 타입(`EmbeddingService`) 수정.
  - `OpenAIClient.generate`의 인자 타입 등 잘못된 부분 교정.
- [x] **8. 도커 환경 설정 교정 (`Dockerfile`)**
  - `CLAUDE.md` 규칙(Python 3.11)에 맞게 베이스 이미지 변경 가능성 검토.
  - `httpx<0.26` 강제 설치 구문을 `pyproject.toml` (Poetry)로 이관.