# 🚀 Soma Agent 추론(Inference) 고도화 가이드

현재 `soma_app`의 추론 로직은 기본적인 RAG 및 Intent Classification 구조가 잘 잡혀 있습니다. 추론 담당자로서 향후 시스템을 운영 수준(Production-ready)으로 끌어올리기 위한 주요 고도화 포인트를 제안합니다.

---

## 1. Function Calling / Tool Calling 도입
현재는 LLM에게 `json_object` 포맷으로 응답하도록 프롬프트로 강제하고 있습니다. 이는 환각(Hallucination)이나 포맷 오류의 가능성이 있습니다.

- **개선 방향**: Upstage Solar 또는 OpenAI의 **Function Calling API**를 직접 사용하도록 `open_ai.py`를 수정합니다.
- **장점**: 
    - 모델이 인자를 추출하는 능력이 훨씬 정교해집니다.
    - JSON 포맷을 맞추지 못해 발생하는 파싱 에러를 근본적으로 방지할 수 있습니다.

## 2. 대화 기록 관리 및 문맥 유지 (Memory)
현재는 단발성 질문(Stateless)만 처리 가능합니다. "그거 다시 알려줘"와 같은 지시 대명사나 이전 대화를 기반으로 한 질문을 처리하지 못합니다.

- **개선 방향**: 
    - `SomaChatRequest`의 `chatSessionId`를 키로 하여 Redis나 DB에 최근 N개의 대화 내역(Message History)을 저장합니다.
    - LLM 호출 시 `messages` 배열에 `[{"role": "user", "content": ...}, {"role": "assistant", "content": ...}]` 형태로 이력을 포함하여 전달합니다.
- **장점**: 연속적인 대화가 가능해져 사용자 경험(UX)이 크게 향상됩니다.

## 3. 스트리밍(Streaming) 응답 적용
현재는 전체 답변이 생성될 때까지 사용자가 대기해야 합니다.

- **개선 방향**: 
    - `FastAPI`의 `StreamingResponse`와 `solar_client.stream_generate`를 연결합니다.
    - 프론트엔드에서 SSE(Server-Sent Events)를 통해 실시간으로 답변이 출력되도록 구현합니다.
- **장점**: 응답 대기 시간(Latency)을 체감상 크게 줄여줍니다.

## 4. 에러 핸들링 및 가드레일 (Guardrails)
부적절한 질문이나 범위를 벗어난 질문에 대한 방어 로직이 필요합니다.

- **개선 방향**: 
    - 의도 분류 결과가 `UNKNOWN`일 때 LLM이 무리하게 답변하지 않고, "제가 도와드릴 수 있는 범위를 벗어난 질문입니다. 소마 공지나 멘토링에 대해 물어봐 주세요."와 같은 표준 응답을 하도록 설정합니다.
- **장점**: 서비스의 정체성을 유지하고 잘못된 정보 제공을 방지합니다.

## 5. 프롬프트 버전 관리 및 평가 (A/B Testing)
프롬프트 수정이 답변 품질에 미치는 영향을 정량적으로 평가해야 합니다.

- **개선 방향**: 
    - `prompts.py` 외에 프롬프트 관리 도구(LangSmith, W&B 등)를 도입하거나 내부적인 프롬프트 버전 관리 체계를 구축합니다.
    - 주요 질문 세트(Golden Dataset)를 만들어 품질 변화를 주기적으로 테스트합니다.
- **장점**: 지속적인 품질 개선이 가능해집니다.
