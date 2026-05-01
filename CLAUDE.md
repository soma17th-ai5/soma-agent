# Claude Code: 프로젝트 (공통 규칙 + 프로젝트별 설정)

<!-- 프로젝트 루트에 이 파일을 CLAUDE.md 로 복사해서 사용하세요. -->
<!-- 상단 공통 규칙은 보일러플레이트 CLAUDE.md와 동일합니다. -->

## 절대 규칙 (예외 없음)
- main/master에 직접 커밋 금지. 항상 브랜치 사용
- 테스트 없이 PR 금지. 증거 = 통과된 테스트 결과 (스크린샷 불허)
- 모든 작업은 GitHub 이슈 번호와 연결
- 커밋 형식: `feat|fix|refactor|docs|test|chore|perf(scope): message [#N]`
- force push 금지. 히스토리 문제 발생 시 반드시 질문
- 불확실한 결정(스키마 변경, API 계약, 인증 로직)은 추측 말고 질문

## 워크플로우
```
/issue → /start <N> → [개발] → /commit → /verify → /done
```

## 슬래시 커맨드
| 커맨드 | 용도 |
|--------|------|
| `/start <N>` | 이슈 N 작업 시작 |
| `/commit` | 스마트 커밋 |
| `/verify` | 7단계 검증 (PR 전 필수) |
| `/done` | verify → push → PR 원스텝 |
| `/pr` | PR 생성 (verify 포함) |
| `/review` | code-reviewer 리뷰 |
| `/issue` | 이슈 생성 |
| `/log` | 의사결정 기록 |
| `/test <file>` | 테스트 생성 |

상세: docs/HOW-TO-USE.md

## 자동 의사결정 감지
대화 중 다음 유형의 결정이 이루어지면 즉시 Bash로 `/tmp/claude-pending-decision.txt`에 기록:
- 기술 스택/라이브러리 선택 (A vs B 비교 후 결정)
- 아키텍처 패턴 선택 (레이어 구조, 모듈 분리 방법)
- API 설계 결정 (응답 형식, 상태코드 규칙)
- 성능/보안 트레이드오프 선택

기록 형식 (append):
```
## [YYYY-MM-DD] BRANCH: 결정 제목

**컨텍스트**: 왜 이 결정이 필요했는가
**결정**: 선택한 방법
**검토한 대안**: 검토했지만 선택하지 않은 것들
**근거**: 이 방법을 선택한 이유
**트레이드오프**: 이 선택의 단점
**이슈**: #N

---
```
세션 종료 시 stop hook이 자동으로 DECISIONS.md에 append함.

## 결정 전 셀프 체크리스트 (다관점)
중요한 결정(스키마/계약/아키 변경) 직전에 한 번 더 다음 관점에서 셀프 체크:
- **PO**: 사용자에게 어떤 가시적 변화? 이 변경이 이슈 의도와 일치하는가?
- **운영**: 롤백 가능한가? 마이그레이션 다운타임/순서? 모니터링 추가 필요?
- **QA**: 회귀 위험 영역? 행동 vs 구현 디테일 테스트?
- **보안**: 인증/인가 영향? PII/시크릿 노출 경로 추가?

하나라도 답이 막히면 추측 말고 질문하거나 `/log`로 결정을 명시.

## 규칙 파일 참조
@.claude/rules/git.md
@.claude/rules/security.md
@.claude/rules/testing.md

---

## 프로젝트별 설정 (아래만 채우면 됨)

**프로젝트명**: [프로젝트명]

### 스택
- **언어**: [Java 21 / Kotlin 1.9 / Python 3.11]
- **프레임워크**: [Spring Boot 3.x / FastAPI / 없음]
- **빌드 도구**: [Gradle 8.x / Maven / pip]
- **테스트**: [JUnit5 + Mockito / pytest / Jest]
- **주요 의존성**: [Redis, Kafka, PostgreSQL 등]

### 명령어
```bash
# 빌드
./gradlew build          # Java/Kotlin
# 또는: ./mvnw compile
# 또는: pip install -e ".[dev]"

# 테스트 전체
./gradlew test           # Java/Kotlin
# 또는: ./mvnw test
# 또는: pytest -v

# 로컬 실행
./gradlew bootRun        # Spring Boot
# 또는: python -m uvicorn app.main:app --reload

# 아키텍처 테스트만
./gradlew test --tests "*ArchitectureTest"
# 또는: pytest tests/test_architecture.py -v
```

### 아키텍처

```
[프로젝트 레이어 구조 다이어그램]
예시 (Spring Boot):
  controller/ ← HTTP 어댑터 (DTO 사용)
  service/    ← 비즈니스 로직
  repository/ ← 데이터 접근
  domain/     ← 순수 도메인 모델
```

**레이어별 역할**:
- `controller/`: [역할 설명]
- `service/`: [역할 설명]
- `repository/`: [역할 설명]
- `domain/`: [역할 설명]

**의존성 방향**: controller → service → repository (역방향 금지)

### API 에러 응답 형식
```json
{
  "code": "DOMAIN_ERROR_CODE",
  "message": "사용자에게 보여줄 메시지"
}
```

### 환경 변수
```bash
# 필수 환경 변수 목록 (값은 .env 파일 또는 팀에게 요청)
DATABASE_URL=
REDIS_URL=
JWT_SECRET=
# ...
```

### 현재 활성 이슈
<!-- Claude: 작업 시작 전 `gh issue list --state open` 실행 -->

### 프로젝트별 주의사항
<!-- 이 프로젝트에서 특히 주의해야 할 것들 -->
- [예: 메시지큐 구현체는 절대 교체하지 말 것. 이유: #12 참고]
- [예: User 도메인 변경 시 반드시 팀에 알릴 것]

### 불확실할 때
이 프로젝트에서 다음 결정은 반드시 질문하세요:
- [예: DB 스키마 변경]
- [예: 외부 API 응답 형식 변경]
- [예: 인증 로직 수정]
