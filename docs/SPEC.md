# SomaAgent — 기술 스펙

> 본 문서는 SomaAgent MVP 구현을 위한 단일 진실 소스(Single Source of Truth)이다.
> 변경 시 반드시 PR로 검토하고, 결정 변경은 `DECISIONS.md`에 함께 기록한다.

---

## 1. 시스템 컨텍스트

### 1.1 구성요소

```
┌──────────────────┐         ┌──────────────────────────────┐
│  Next.js Chat UI │ ──────► │   FastAPI App (soma-agent)   │
│ (별도 레포/배포) │         │                              │
└──────────────────┘         │  ┌────────────────────────┐  │
                             │  │  Agent Orchestrator    │  │
                             │  │  (LangGraph)           │  │
                             │  └─────────┬──────────────┘  │
                             │            │                 │
                             │  ┌─────────▼──────────────┐  │
                             │  │  Tool Layer            │  │
                             │  │  - opensoma.*          │  │
                             │  │  - rag.*               │  │
                             │  │  - webex.*             │  │
                             │  │  - calendar.* (mock)   │  │
                             │  └─────────┬──────────────┘  │
                             │            │                 │
                             │  ┌─────────▼──────────────┐  │
                             │  │  Adapter Layer         │  │
                             │  │  (외부 시스템 추상화)  │  │
                             │  └─────────┬──────────────┘  │
                             │            │                 │
                             │  ┌─────────▼──────────────┐  │
                             │  │  Scheduler             │  │
                             │  │  (APScheduler)         │  │
                             │  └────────────────────────┘  │
                             └──────────────────────────────┘
                                          │
            ┌─────────────────────────────┼─────────────────────────────┐
            ▼                             ▼                             ▼
      ┌──────────┐              ┌──────────────┐              ┌────────────────┐
      │  MySQL 8 │              │   Qdrant     │              │  Upstage Solar │
      │  (RDB)   │              │  (VectorDB)  │              │  (LLM/Embed)   │
      └──────────┘              └──────────────┘              └────────────────┘

                              (외부 시스템)
                                      ▲
                                      │
                          ┌───────────┴────────────┐
                          ▼                        ▼
                  ┌──────────────────┐     ┌──────────────┐
                  │ OpenSoma Sidecar │     │  Webex API   │
                  │ (Bun + TS SDK)   │     │              │
                  │  HTTP RPC        │     └──────────────┘
                  └────────┬─────────┘            ▲
                           │                      │
                           ▼                      │
                  ┌──────────────────┐            │
                  │  소마 홈페이지   │            │
                  │  (HTML 스크래핑) │            │
                  └──────────────────┘            │
                                                  │
                            (FastAPI app가 webex_client로 직접 호출)─┘
```

### 1.2 외부 의존성

| 시스템 | 용도 | 인증 방식 | 호출 주체 |
|---|---|---|---|
| **OpenSoma Sidecar** | 소마 홈페이지 wrapper (Bun + TS SDK) | 내부 HTTP, 동일 네트워크 | FastAPI app |
| 소마 홈페이지 | 공지·멘토링·접수내역 (HTML 스크래핑) | 사용자 ID/PW 또는 세션 쿠키 | OpenSoma Sidecar |
| Webex API | 공용 스페이스 메시지 | **운영자 OAuth/Personal Access Token** | 스케줄러 |
| Upstage Solar | LLM/Embedding | API Key (서비스 단일) | 모든 LLM 호출 |
| Google Calendar | (mock) | — | mock 어댑터 |

**OpenSoma Sidecar**: `github.com/opensoma/opensoma`의 TS SDK는 Python에서 직접 import할 수 없어 별도 컨테이너로 띄우고 좁은 HTTP RPC로 호출한다. 동일 docker-compose 네트워크 안에서만 노출(외부 비공개). FastAPI 앱은 이 sidecar에만 의존하고 소마 홈페이지를 직접 보지 않는다.

**Webex 인증**: Bot token은 그룹 룸에서 멘션된 메시지만 읽는 제약이 있어 채택하지 않는다. 운영자 본인 계정의 Personal Access Token 또는 Integration Token(`spark:rooms_read spark:messages_read`)을 사용한다.

### 1.3 인증 흐름

1. 클라이언트(Next.js)가 SomaAgent의 `POST /auth/login`에 ID/PW를 보낸다. (또는 직접 sidecar로 보낼 수 있지만 MVP는 백엔드 위임.)
2. SomaAgent는 ID/PW를 sidecar `POST /sessions` 로 전달, sidecar가 소마 홈페이지에 로그인하고 `JSESSIONID`+`csrfToken`을 받아 `session_id`(우리가 발급한 핸들)와 매핑하여 sidecar 메모리에 보관.
3. SomaAgent는 응답으로 `session_id`만 클라이언트에 돌려준다. **세션 쿠키 원본은 sidecar에만 머문다.** 클라이언트는 `X-Soma-Session: <session_id>` 헤더로 이후 요청을 보낸다.
4. SomaAgent의 OpenSoma 어댑터는 sidecar에 호출할 때 `X-Soma-Session`을 함께 보내고 sidecar가 매핑된 쿠키로 실제 호출 수행.
5. **SomaAgent도 클라이언트도 ID/PW와 쿠키 원본을 저장하지 않는다.** sidecar는 인메모리 매핑만 보관하고 재시작 시 휘발.
6. 처음 인증 성공 시 sidecar가 반환하는 `whoami()` 결과(`soma_user_id`, 이메일, 역할 — 가능한 경우)를 받아 `users` 테이블에 upsert한다.

**세션 만료 처리**: sidecar는 OpenSoma 응답에서 세션 만료 신호(본문 키워드 `세션`·`만료` 또는 로그인 페이지 HTML)를 감지하면 `401 SESSION_EXPIRED`로 통일해 반환. SomaAgent는 이를 받아 클라이언트에 `X-Soma-Session-Expired: true` 헤더와 함께 401 응답.

---

## 2. 디렉토리 구조

```
soma-agent/
├── app/
│   ├── main.py                  # FastAPI 엔트리포인트
│   ├── config.py                # pydantic-settings 기반 환경설정
│   ├── api/
│   │   ├── __init__.py
│   │   ├── deps.py              # 공통 의존성 (DB 세션, 인증 추출)
│   │   ├── chat.py              # POST /chat (메인 대화 엔드포인트)
│   │   ├── auth.py              # POST /auth/login (OpenSoma 로그인 위임 — 선택)
│   │   └── health.py            # GET /healthz, /readyz
│   ├── agent/
│   │   ├── __init__.py
│   │   ├── graph.py             # LangGraph 그래프 정의
│   │   ├── nodes/
│   │   │   ├── router.py        # 요청 분류
│   │   │   ├── tool_executor.py # Tool 호출 (≤2개 강제)
│   │   │   └── synthesizer.py   # ToolResult → ChatMessage
│   │   ├── prompts.py           # 시스템 프롬프트 모음
│   │   └── memory.py            # 인메모리 세션 메모리
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── base.py              # Tool 추상 클래스 + ToolResult 모델
│   │   ├── registry.py          # tool 등록·조회
│   │   ├── knowledge.py         # knowledge.search (통합 RAG)
│   │   ├── mentoring.py         # opensoma.mentoring.{list,get,apply,cancel}
│   │   ├── notice.py            # opensoma.notice.get
│   │   ├── application.py       # opensoma.application.history
│   │   └── calendar.py          # calendar.invite.create (mock)
│   ├── adapters/
│   │   ├── __init__.py
│   │   ├── opensoma_client.py   # OpenSoma sidecar HTTP RPC 어댑터
│   │   ├── webex_client.py      # Webex API 어댑터
│   │   ├── solar_client.py      # Solar LLM/Embedding 어댑터
│   │   ├── qdrant_client.py     # Qdrant 어댑터
│   │   └── calendar_mock.py     # 캘린더 mock
│   ├── domain/
│   │   ├── __init__.py
│   │   ├── enums.py             # 모든 enum (작아서 한 파일)
│   │   ├── models/              # SQLAlchemy ORM (도메인별)
│   │   │   ├── __init__.py
│   │   │   ├── user.py
│   │   │   ├── notice.py        # Notice + NoticeAttachment
│   │   │   ├── mentoring.py
│   │   │   ├── webex.py         # WebexRoom + WebexMessage
│   │   │   └── sync_state.py
│   │   ├── schemas/             # Pydantic 요청/응답 DTO
│   │   │   ├── __init__.py
│   │   │   ├── chat.py
│   │   │   ├── mentoring.py
│   │   │   └── notice.py
│   │   └── contracts/           # 내부 계약 (ToolResult / ChatMessage)
│   │       ├── __init__.py
│   │       ├── tool_result.py   # ToolResult / Artifact / Action* / ToolError
│   │       ├── chat.py          # ChatMessage / ChatUIBlock
│   │       └── source.py
│   ├── services/                # 비즈니스 로직 (도메인별 단일 파일, 함수 위주)
│   │   ├── __init__.py
│   │   ├── auth.py              # 사용자 upsert
│   │   ├── notice.py            # sync + get_with_attachments
│   │   ├── mentoring.py         # sync + get_live + apply + cancel
│   │   ├── webex.py             # sync (조회는 knowledge에 위임)
│   │   ├── application.py       # history + cache invalidation
│   │   ├── knowledge.py         # 통합 RAG: search
│   │   ├── rag_indexer.py       # chunking + embedding + qdrant upsert (공용 헬퍼)
│   │   └── calendar.py          # mock invite
│   ├── scheduler/
│   │   ├── __init__.py
│   │   └── jobs.py              # APScheduler 잡 정의
│   ├── db/
│   │   ├── __init__.py
│   │   ├── session.py           # SQLAlchemy engine/session
│   │   └── migrations/          # Alembic
│   ├── observability/
│   │   ├── __init__.py
│   │   ├── logging.py           # structlog 설정
│   │   └── tracing.py           # trace_id 미들웨어
│   └── utils/
│       ├── __init__.py
│       └── hashing.py           # HMAC 익명화
├── tests/
│   ├── conftest.py
│   ├── test_architecture.py     # 레이어 의존성 강제
│   ├── unit/
│   │   ├── tools/
│   │   ├── services/
│   │   └── agent/
│   ├── integration/
│   │   ├── test_chat_flow.py    # 시연 시나리오 5개
│   │   └── test_sync_jobs.py
│   └── fixtures/
├── docs/
│   ├── SPEC.md                  # ← 본 문서
│   ├── HOW-TO-USE.md
│   └── DECISIONS.md
├── opensoma-sidecar/             # Bun 미니 HTTP 서버 (TS SDK wrapper)
│   ├── src/
│   │   ├── server.ts             # POST /sessions, /notice/*, /mentoring/*, /application/*
│   │   ├── session_store.ts      # session_id ↔ {JSESSIONID, csrfToken} 인메모리 매핑
│   │   └── error_mapping.ts      # AuthenticationError → 401 SESSION_EXPIRED 등
│   ├── package.json              # opensoma sdk 의존성
│   ├── tsconfig.json
│   └── Dockerfile
├── docker/
│   ├── Dockerfile                # FastAPI app
│   ├── docker-compose.yml        # MySQL + Qdrant + app + opensoma-sidecar
│   └── docker-compose.dev.yml
├── pyproject.toml
├── alembic.ini
├── .env.example
├── .gitignore
├── AGENTS.md
└── CLAUDE.md
```

> sidecar는 같은 레포(monorepo)로 관리. 별도 빌드/배포지만 docker-compose로 묶어 같은 사설 네트워크에서 통신. 외부 노출 안 함.

### 2.1 레이어 의존성 규칙

```
api/   →   agent/   →   tools/   →   adapters/   →   외부
                       ↘             ↘
                        services/  ←  db/  / qdrant_client
domain/ 은 모든 레이어에서 import 가능 (역방향 import 금지)
```

- `tools/` 는 `services/` 만 호출 (얇은 래퍼). `adapters/` 직접 호출 금지.
- `services/` 는 `adapters/` + `db/` + `domain/` 만 사용. 함수 위주, 의존성은 인자로 주입.
- `adapters/` 는 외부 라이브러리/HTTP 호출만, `domain/` 만 import.
- `domain/` 은 모든 레이어에서 import 가능. 역방향 import 금지.
- `tests/test_architecture.py` 에서 AST로 강제.

**서비스 파일 분할 규칙**: 도메인당 한 파일로 시작. 단일 파일이 ~400줄 넘으면 도메인 폴더로 승격(`services/mentoring/{sync,actions,search}.py`). 미리 쪼개지 않는다.

---

## 3. 도메인 모델 / DB 스키마

> 컬럼은 OpenSoma TS SDK(`packages/opensoma/types`)와 Webex API 공식 docs 응답 형태에 맞춰 정렬됨.
> 구체 명세는 sidecar PoC 첫 PR에서 실측으로 한 번 더 확정.

### 3.1 MySQL 스키마

#### `users`

OpenSoma `whoami()` 응답: `{userId, userNm, userNo, userGb}`.
**`userId`는 로그인 username(=이메일)** 이고 별도의 시스템 ID가 아님. `userNo`가 32자 hex GUID 형태의 내부 ID.

| 컬럼 | 타입 | OpenSoma 필드 | 비고 |
|---|---|---|---|
| `id` | BIGINT PK AUTO_INCREMENT | — | 우리 내부 PK |
| `soma_user_id` | VARCHAR(255) UNIQUE NOT NULL | `userId` | 로그인 username (이메일 형태) |
| `user_no` | CHAR(32) UNIQUE NOT NULL | `userNo` | OpenSoma 내부 GUID (hex) |
| `user_name` | VARCHAR(100) | `userNm` | 한글 이름 |
| `role` | ENUM('TRAINEE','MENTOR','EXPERT','OPERATOR') NOT NULL | `userGb` 매핑 | `C`→TRAINEE, `T`→MENTOR. EXPERT/OPERATOR는 운영자 수동 부여 |
| `created_at` | DATETIME NOT NULL |
| `updated_at` | DATETIME NOT NULL |

> `email` 컬럼은 별도로 두지 않음. `soma_user_id` 가 곧 이메일 (실측 결과 `sueelly@naver.com` 형태).

#### `notices`
OpenSoma `NoticeListItem`/`NoticeDetail` 매핑. 첨부 별도 필드 없으므로 content HTML에서 파싱한다.

| 컬럼 | 타입 | OpenSoma 필드 | 비고 |
|---|---|---|---|
| `id` | BIGINT PK |
| `notice_id` | BIGINT UNIQUE NOT NULL | `id` | OpenSoma는 number |
| `title` | VARCHAR(500) | `title` |
| `author` | VARCHAR(200) | `author` |
| `created_at_text` | VARCHAR(50) | `createdAt` | 실측 포맷: `"YYYY.MM.DD HH:MM:SS"` (점 구분, KST) |
| `posted_at` | DATETIME NULLABLE | (파싱) | `created_at_text`를 KST로 정규화. 실패 시 NULL |
| `content_html` | MEDIUMTEXT | `content` | sanitize 안 함 |
| `content_text` | MEDIUMTEXT | (파생) | HTML 태그 제거된 plain text. RAG 인덱싱용 |
| `detail_url` | VARCHAR(1000) | (구성) |
| `content_hash` | CHAR(64) | SHA256(title+content_html) |
| `last_fetched_at` | DATETIME |
| `is_active` | BOOLEAN DEFAULT TRUE |

#### `notice_attachments`
| 컬럼 | 타입 | 비고 |
|---|---|---|
| `id` | BIGINT PK |
| `notice_id` | BIGINT FK → notices.notice_id |
| `file_name` | VARCHAR(500) | content HTML에서 anchor text |
| `file_url` | VARCHAR(1000) | href 추출 |
| `file_type` | VARCHAR(20) | URL 확장자 또는 Content-Type |
| `extracted_text` | MEDIUMTEXT NULLABLE | PDF/문서 텍스트 추출 결과 |
| `extracted_at` | DATETIME NULLABLE |

#### `mentorings`

실측 응답 (Q1=확정):
```json
{
  "id": 10786,
  "title": "...",
  "type": "멘토 특강",
  "registrationPeriod": {"start": "2026-04-27", "end": "2026-05-31"},
  "sessionDate": "2026-05-31",
  "sessionTime": {"start": "20:00", "end": "22:00"},
  "attendees": {"current": 20, "max": 20},
  "approved": true,
  "status": "마감",
  "author": "...",
  "createdAt": "2026-04-26"
}
```

내가 처음에 가정한 단순 문자열들이 모두 **객체** 또는 boolean이었음. 이에 맞춰 컬럼 분할.

| 컬럼 | 타입 | OpenSoma 필드 | 비고 |
|---|---|---|---|
| `id` | BIGINT PK | — | 우리 PK |
| `mentoring_id` | BIGINT UNIQUE NOT NULL | `id` | OpenSoma number |
| `title` | VARCHAR(500) | `title` |
| `mentoring_type` | VARCHAR(50) | `type` | 한글값 (예: `"멘토 특강"`, `"자유 멘토링"`) — ENUM 아님 |
| `registration_start_at` | DATETIME | `registrationPeriod.start` | `YYYY-MM-DD` 파싱 |
| `registration_end_at` | DATETIME | `registrationPeriod.end` |
| `session_date` | DATE | `sessionDate` | `YYYY-MM-DD` |
| `session_start_time` | TIME | `sessionTime.start` | `HH:MM` |
| `session_end_time` | TIME | `sessionTime.end` |
| `session_started_at` | DATETIME NULLABLE | (파생) | `session_date + session_start_time` |
| `attendees_current` | INT | `attendees.current` |
| `attendees_max` | INT | `attendees.max` |
| `approved` | BOOLEAN | `approved` |
| `mentoring_status` | VARCHAR(20) | `status` | 한글값 (`"마감"`, `"모집중"`, `"진행중"` 등 — ENUM 아님) |
| `author` | VARCHAR(200) | `author` |
| `created_at_text` | VARCHAR(50) | `createdAt` | 실측 포맷: `"YYYY-MM-DD"` (notice는 `"."` 구분, mentoring은 `"-"` — 다름!) |
| `content_html` | MEDIUMTEXT NULLABLE | `content` (detail에만) |
| `venue` | VARCHAR(500) NULLABLE | `venue` (detail에만) |
| `detail_url` | VARCHAR(1000) |
| `content_hash` | CHAR(64) |
| `last_fetched_at` | DATETIME |
| `is_active` | BOOLEAN DEFAULT TRUE |

> **주의**: `mentoring_type` 과 `mentoring_status` 는 OpenSoma 응답값이 한글 자유문자열이라 ENUM으로 강제하지 않음. 새 값 등장 시 자동 흡수.

> 카테고리·태그·정원 등 우리가 가상으로 가정했던 필드는 OpenSoma에 없음. 분야 검색 품질이 부족하면 description LLM 키워드 추출은 v2로.

#### `mentoring_applicants`
멘토링 상세에 포함되는 신청자 목록. `MentoringDetail.applicants[]` 매핑. 익명화 적용.

| 컬럼 | 타입 | OpenSoma 필드 | 비고 |
|---|---|---|---|
| `id` | BIGINT PK |
| `mentoring_id` | BIGINT FK |
| `applicant_name_hash` | CHAR(32) | `name` (HMAC) | 평문 이름 저장 안 함 |
| `applied_at_text` | VARCHAR(50) | `appliedAt` |
| `cancelled_at_text` | VARCHAR(50) NULLABLE | `cancelledAt` |
| `applicant_status` | VARCHAR(50) | `status` |
| `collected_at` | DATETIME |

#### `applications`
사용자별 접수 내역 — **취소 호출에 필요한 ID 2개를 보관**한다 (`applySn`+`qustnrSn`).

| 컬럼 | 타입 | OpenSoma 필드 | 비고 |
|---|---|---|---|
| `id` | BIGINT PK |
| `soma_user_id` | VARCHAR(64) NOT NULL |
| `apply_sn` | BIGINT NOT NULL | `id` (history) | 취소 키 1 |
| `qustnr_sn` | BIGINT NULLABLE | (mentoring detail에서 매핑) | 취소 키 2 — 미매핑 시 cancel 시점 sidecar에 위임 |
| `category` | VARCHAR(100) | `category` |
| `title` | VARCHAR(500) | `title` |
| `target_url` | VARCHAR(1000) | `url` |
| `author` | VARCHAR(200) | `author` |
| `session_date_text` | VARCHAR(50) | `sessionDate` |
| `applied_at_text` | VARCHAR(50) | `appliedAt` |
| `application_status` | VARCHAR(50) | `applicationStatus` |
| `approval_status` | VARCHAR(50) | `approvalStatus` |
| `application_detail` | TEXT NULLABLE | `applicationDetail` |
| `note` | TEXT NULLABLE | `note` |
| `cached_at` | DATETIME | TTL 5분 |
| UNIQUE(`soma_user_id`, `apply_sn`) |

> `applications`는 캐시 성격이지만 cancel을 위해 두 ID 모두 필요해서 별도 테이블로 승격함. 신청/취소 직후 해당 사용자 행 모두 삭제 후 다음 조회 시 재채움.

#### `webex_rooms`

| 컬럼 | 타입 | Webex 필드 |
|---|---|---|
| `id` | BIGINT PK |
| `room_id` | VARCHAR(255) UNIQUE NOT NULL | `id` |
| `room_name` | VARCHAR(500) | `title` |
| `room_type` | ENUM('group','direct') | `type` | MVP 'group'만 수집 |
| `is_locked` | BOOLEAN | `isLocked` |
| `is_public` | BOOLEAN | `isPublic` |
| `is_announcement_only` | BOOLEAN | `isAnnouncementOnly` |
| `team_id` | VARCHAR(255) NULLABLE | `teamId` |
| `creator_key` | CHAR(32) NULLABLE | `creatorId` (HMAC) |
| `description` | TEXT NULLABLE | `description` |
| `room_created_at` | DATETIME(3) | `created` |
| `last_activity_at` | DATETIME(3) NULLABLE | `lastActivity` | 동기화 워터마크 |
| `last_synced_at` | DATETIME(3) NULLABLE | (우리) |

#### `webex_messages`

| 컬럼 | 타입 | Webex 필드 |
|---|---|---|
| `id` | BIGINT PK |
| `message_id` | VARCHAR(255) UNIQUE NOT NULL | `id` |
| `room_id` | VARCHAR(255) NOT NULL FK | `roomId` |
| `room_type` | ENUM('group','direct') | `roomType` | denormalized |
| `parent_id` | VARCHAR(255) NULLABLE | `parentId` | 스레드 |
| `sender_key` | CHAR(32) | `personId` (HMAC) |
| `is_bot_sender` | BOOLEAN DEFAULT FALSE | (people API 또는 `@webex.bot` 휴리스틱) |
| `text` | MEDIUMTEXT NULLABLE | `text` |
| `markdown` | MEDIUMTEXT NULLABLE | `markdown` |
| `html` | MEDIUMTEXT NULLABLE | `html` |
| `mentioned_person_keys` | JSON NULLABLE | `mentionedPeople` (각 HMAC) |
| `mentioned_groups` | JSON NULLABLE | `mentionedGroups` |
| `files` | JSON NULLABLE | `files` (URL 배열) |
| `attachments` | JSON NULLABLE | `attachments` (Adaptive Cards) |
| `created_at` | DATETIME(3) | `created` |
| `edited_at` | DATETIME(3) NULLABLE | `updated` | Webex `updated`는 *수정된 메시지에만* 존재 |
| `collected_at` | DATETIME(3) |

> 인덱스 권장: `(room_id, created_at)`, `(parent_id)`, `(edited_at)`.

#### `sync_state`
잡별 마지막 실행/성공 시각 추적.

| 컬럼 | 타입 |
|---|---|
| `job_name` | VARCHAR(100) PK | 'notices', 'mentorings', 'webex' |
| `last_run_at` | DATETIME |
| `last_success_at` | DATETIME |
| `last_error` | TEXT NULLABLE |

> 신청/취소 직후에는 해당 사용자의 `applications` 행을 즉시 삭제한다.

### 3.2 Qdrant 컬렉션

단일 컬렉션 `soma_chunks` 사용, 메타데이터 필터로 분리.

```python
{
  "collection_name": "soma_chunks",
  "vector_size": 4096,           # Solar embedding-passage/query 차원 (실측 확정)
  "distance": "Cosine",
  "payload_schema": {
    "chunk_id": "keyword",         # UUID
    "source_type": "keyword",      # NOTICE | NOTICE_PDF | MENTORING | WEBEX_MESSAGE
    "source_id": "keyword",        # 원천 ID (notice_id / mentoring_id / message_id)
    "title": "text",
    "text": "text",                # 검색·표시용 원문 chunk
    "official": "bool",            # OpenSoma 출처면 true, Webex면 false
    "room_name": "keyword",        # WEBEX_* 만
    "created_at": "datetime",      # 원천 작성 시각
    "collected_at": "datetime",    # 우리 수집 시각
    "source_url": "keyword",
    "source_ref": "keyword"        # 외부 시스템에 직접 링크 못 거는 경우의 식별자
  }
}
```

검색 시 `source_type`, `official` 필드로 필터링.

### 3.3 OpenSoma Sidecar HTTP 인터페이스

FastAPI 앱 ↔ sidecar 사이의 좁은 RPC. 모든 응답은 JSON, 에러는 `{code, message}` 표준 형식. 통신은 사설 네트워크(`opensoma-sidecar:3000`)로만.

| Method | Path | Body | 200 응답 | 에러 코드 |
|---|---|---|---|---|
| `POST` | `/sessions` | `{username, password}` | `{session_id, soma_user_id, email?, role?}` | `INVALID_CREDENTIALS` |
| `DELETE` | `/sessions/{session_id}` | — | `204` | — |
| `GET` | `/whoami` | (header `X-Soma-Session`) | `{soma_user_id, email?, role?}` | `SESSION_EXPIRED` |
| `GET` | `/notice?page=N` | | `{items: NoticeListItem[], pagination}` | `SESSION_EXPIRED` |
| `GET` | `/notice/{id}` | | `NoticeDetail` | `SESSION_EXPIRED`, `NOT_FOUND` |
| `GET` | `/mentoring?status=&type=&search=&page=` | | `{items: MentoringListItem[], pagination}` | `SESSION_EXPIRED` |
| `GET` | `/mentoring/{id}` | | `MentoringDetail` | |
| `POST` | `/mentoring/{id}/apply` | | `{apply_sn, qustnr_sn}` | `ALREADY_APPLIED`, `CLOSED` |
| `POST` | `/mentoring/cancel` | `{apply_sn, qustnr_sn}` | `204` | `NOT_FOUND` |
| `GET` | `/application/history?page=` | | `{items: ApplicationHistoryItem[], pagination}` | |

응답 객체 형태는 OpenSoma TS SDK의 타입을 그대로 JSON 직렬화. snake_case 변환은 sidecar에서 하지 않고 FastAPI 어댑터(`opensoma_client.py`)에서 처리.

**세션 만료 통일**: sidecar가 OpenSoma의 `AuthenticationError`(본문 키워드/HTML 휴리스틱) 검출 시 `401 {code: "SESSION_EXPIRED"}`로 반환. FastAPI 앱은 이를 받아 사용자에게 재로그인 유도.

---

## 4. Tool 카탈로그

모든 tool은 `app/tools/base.py`의 `Tool` 추상 클래스를 상속하며 다음 시그니처를 따른다.

```python
class Tool(Protocol):
    name: str            # e.g. "opensoma.mentoring.apply"
    domain: str          # knowledge | opensoma | calendar
    operation: str       # search | list | get | apply | cancel | ...
    requires_auth: bool  # OpenSoma 헤더 필요 여부

    async def run(self, params: dict, ctx: ToolContext) -> ToolResult: ...
```

### 4.1 설계 원칙

- **검색은 통합**: 공지/멘토링/Webex 모두 `knowledge.search`로 통합한다. Qdrant 단일 컬렉션·메타데이터 필터·검색 로직이 동일하기 때문에 도메인별로 tool을 쪼개지 않는다.
- **OpenSoma 직통은 "현재 상태가 중요한 경우만"**: 멘토링 라이브 목록·상세, 신청/취소, 접수 내역, 공지 단일 정확 조회.
- **내부 잡은 tool이 아니다**: Webex 메시지 동기화·요약 생성, 공지/멘토링 크롤링은 `services/`의 함수로만 존재하고 사용자 호출 경로(=Agent의 tool 카탈로그)에는 노출하지 않는다.

### 4.2 Tool 목록 (8개)

| Tool 이름 | 입력 | 출력 데이터 | 인증 | 비고 |
|---|---|---|---|---|
| `knowledge.search` | `{query: str, source_types?: ["NOTICE","NOTICE_PDF","MENTORING","WEBEX_MESSAGE"], official_only?: bool=false, room_name?: str, k?: int=5}` | `Chunk[]` | — | 모든 RAG 진입점 |
| `opensoma.mentoring.list` | `{filters?: dict, limit?: int}` | `Mentoring[]` | ✓ | 라이브 목록 (현재 상태 정확) |
| `opensoma.mentoring.get` | `{mentoring_id: str}` | `MentoringDetail` | ✓ | 라이브 상세 |
| `opensoma.mentoring.apply` | `{mentoring_id: str}` | `ApplyResult` | ✓ | 직전 `.get` 재검증 강제 |
| `opensoma.mentoring.cancel` | `{apply_sn: int, qustnr_sn: int}` | `CancelResult` | ✓ | OpenSoma는 ID 2개 필요. agent는 `applications` 캐시에서 매핑 |
| `opensoma.application.history` | `{}` | `Application[]` | ✓ | TTL 5분 캐시 |
| `opensoma.notice.get` | `{notice_id: str}` | `NoticeDetail` (첨부 포함) | ✓ | 정확 조회용 |
| `calendar.invite.create` | `{title, start_at, end_at, description?, location?}` | `MockInviteResult` | — | mock |

### 4.3 의도 → tool 매핑 가이드

| 사용자 의도 예시 | 1차 tool | 후속 |
|---|---|---|
| "이번 주 공지 알려줘" | `knowledge.search(source_types=["NOTICE","NOTICE_PDF"], official_only=true)` | — |
| "공지 N번 자세히" | `opensoma.notice.get` | — |
| "백엔드 멘토링 찾아줘" (의미 검색) | `knowledge.search(source_types=["MENTORING"])` | 사용자 의향 시 `opensoma.mentoring.get` |
| "지금 신청 가능한 멘토링" (현재 상태) | `opensoma.mentoring.list` | — |
| "이거 신청해줘" | `opensoma.mentoring.get` (재검증) | `ActionProposal { MENTORING_APPLY }` 반환. 사용자 확인 후 `/actions/execute`로 실제 실행 |
| "내 접수 내역" | `opensoma.application.history` | — |
| "Webex에서 X 얘기 정리" | `knowledge.search(source_types=["WEBEX_MESSAGE"])` | — |

### 4.4 액션 실행 정책

도메인 액션(신청/취소)은 채팅과 분리된 전용 엔드포인트 `POST /api/v1/actions/execute`로 위임한다 (§6.4). 채팅 응답에서는 *제안만* 하고 직접 실행하지 않는다.

- **`/chat` 측**: router가 신청/취소 의도를 감지해도 `opensoma.mentoring.apply` / `.cancel` tool은 호출하지 않는다. 대신 `opensoma.mentoring.get`으로 현재 상태를 가져와 `ActionProposal { actionType, label, payload }`을 채팅 응답의 `actions[]`에 담아 반환.
- **`/actions/execute` 측**: 사용자가 카드의 액션 버튼을 누르면 프론트가 받은 `ActionProposal` 페이로드를 그대로 이 엔드포인트로 보낸다. 백엔드는:
  1. `opensoma.mentoring.get`으로 직전 상태 재검증 (`OPEN`/정원 미달 등)
  2. `opensoma.mentoring.apply` / `.cancel` 호출
  3. `MENTORING_APPLY` 성공 시 `calendar.invite.create` (mock) 후속 호출 — 캘린더 실패는 신청 롤백 안 함, 응답 `data.calendarInvite.status = "failed"`로 부분 실패 표시
- **확인 모달**: `requiresConfirmation: true`인 경우 프론트가 자체 모달로 사용자 확인 → 확인 시에만 `/actions/execute` 호출. 백엔드는 두 번 묻지 않는다.
- **카드 직접 클릭**: 채팅을 거치지 않고 멘토링 카드 등 UI에서 바로 신청 버튼을 누르는 경우도 동일하게 `/actions/execute` 호출. 프론트는 `mentoringId`만 알면 됨 (취소의 경우 백엔드가 `applications` 캐시에서 `applySn`+`qustnrSn` 매핑).

---

## 5. Agent 그래프 (LangGraph)

### 5.1 노드

```
                  ┌─────────────┐
   user input ─►  │   router    │
                  └──────┬──────┘
                         │  intents + tool plan
                         ▼
                  ┌─────────────┐
                  │ tool_       │
                  │ executor    │  ← 최대 2개 tool 호출, 카운트 강제
                  └──────┬──────┘
                         │  ToolResult[]
                         ▼
                  ┌─────────────┐
                  │ synthesizer │  ← ToolResult → ChatMessage
                  └──────┬──────┘
                         │
                         ▼
                  user-facing
                  ChatMessage
```

### 5.2 router

- 입력: 사용자 메시지, 직전 후보 목록(클라가 매 요청에 재전송), 세션 메모리 최근 N(=5)턴.
- 출력: `intent` + `tool_plan: [{tool, params}, ...]` (최대 2개).
- 구현: Solar LLM에 시스템 프롬프트 + tool 카탈로그 JSON Schema → 함수 호출 형식으로 plan 받음.

### 5.3 tool_executor

- 입력: `tool_plan`.
- 동작:
  1. plan 길이가 2 초과면 잘라내고 `ToolResult{status:"partial"}`로 안내 메시지 추가.
  2. 각 tool 순차 실행 (병렬 시 OpenSoma 세션 동시성 안전 보장이 어려워 순차 기본).
  3. tool 실패도 `ToolResult{status:"failed"}` 로 흡수 — 그래프는 끝까지 진행.
- 출력: `ToolResult[]`.

### 5.4 synthesizer

- 입력: `ToolResult[]`, 사용자 원문.
- 동작:
  - 모든 `Source` 를 합쳐 `ChatMessage.sources`에 채움 (중복 제거).
  - `ToolResult.artifacts` 를 매핑하여 `ui` 블록 생성.
  - `action` 이 `needs_confirmation` 인 것만 `actions`에 노출.
  - LLM은 **요약문 생성**에만 사용. 사실 데이터는 ToolResult 그대로 전달.
- 프롬프트 규칙: §6 참고.

### 5.5 메모리

- `app/agent/memory.py` 에서 `dict[session_id, deque[ChatTurn]]` 유지, 최근 10턴.
- 서버 재시작 시 유실 허용.

---

## 6. 응답 계약

### 6.1 ToolResult (백엔드 내부)

```ts
type ToolResult<TData = unknown> = {
  tool: string;
  domain: "opensoma" | "rag" | "webex" | "calendar" | "system";
  operation: string;
  status: "success" | "partial" | "failed" | "needs_confirmation";
  data?: TData;
  sources?: Source[];
  artifacts?: Artifact[];
  action?: ActionProposal | ActionResult;
  error?: ToolError;
  metadata?: Record<string, unknown>;
};

type Source = {
  id?: string;
  type: "notice" | "notice_pdf" | "mentoring" | "application"
      | "webex_message" | "webex_summary" | "calendar" | "other";
  title: string;
  url?: string;
  createdAt?: string;
  collectedAt?: string;
  official: boolean;
  rawRef?: string;
};

type Artifact = {
  type: "card" | "list" | "table" | "markdown" | "confirmation";
  title?: string;
  items?: unknown[];
  content?: string;
};

type ActionType = "MENTORING_APPLY" | "MENTORING_CANCEL";

type ActionProposal = {
  actionType: ActionType;
  label: string;                          // 사용자 노출 버튼 라벨
  payload: ActionPayload;                 // /actions/execute에 그대로 재전송
  requiresConfirmation: boolean;          // true면 프론트가 자체 확인 모달 표시
  expiresAt?: string;                     // ISO 8601, 제안 유효 시각 (선택)
};

type ActionPayload =
  | { mentoringId: string }                                    // MENTORING_APPLY
  | { mentoringId: string }                                    // MENTORING_CANCEL — 백엔드가 applications 캐시에서 applySn+qustnrSn 매핑
  | { mentoringId: string; applySn: number; qustnrSn: number }; // MENTORING_CANCEL — 매핑 정보를 이미 알고 있을 때

type ActionResult = {
  actionType: ActionType;
  status: "success" | "failed";
  message: string;
  data?: Record<string, unknown>;
};

type ToolError = {
  code: string;
  message: string;
  recoverable: boolean;
};
```

### 6.2 ChatMessage (프론트 응답)

```ts
type ChatMessage = {
  answer: string;
  status: "success" | "partial" | "failed" | "needs_confirmation";
  sources: Source[];
  ui: ChatUIBlock[];
  actions?: ActionProposal[];
  trace_id: string;
};

type ChatUIBlock =
  | { type: "source_list"; sources: Source[] }
  | { type: "mentoring_cards"; items: MentoringCard[] }
  | { type: "notice_list"; items: NoticeCard[] }
  | { type: "webex_summary"; items: WebexSummaryItem[] }
  | { type: "action_result"; results: ActionResult[] };
```

### 6.3 HTTP 엔드포인트 — 채팅

```
POST /api/v1/chat
Headers:
  X-Soma-Session: <session_id>          # /auth/login에서 발급
  X-Session-Id:   <UUID, 프론트가 발급해 유지>
Body:
{
  "message": "이번 주 백엔드 멘토링 찾아줘",
  "candidates_context"?: [...]          // 직전 후보 목록 그대로 재전송
}
Response: ChatMessage
```

> 채팅에서는 신청/취소를 *제안만* 한다. 실제 실행은 §6.4 `/actions/execute` 호출.

### 6.4 HTTP 엔드포인트 — 액션 실행

도메인 액션(신청/취소)을 명시적으로 실행하는 전용 엔드포인트. 채팅 응답의 `ActionProposal`을 그대로 페이로드로 사용하거나, 카드 UI에서 직접 호출 가능.

```
POST /api/v1/actions/execute
Headers:
  X-Soma-Session: <session_id>
  X-Session-Id:   <UUID>
Body:
{
  "actionType": "MENTORING_APPLY",       // ActionType enum
  "payload": { "mentoringId": "M123" }   // ActionPayload
}
```

**200 응답: `ActionExecutionResponse`**

```ts
type ActionExecutionResponse = {
  actionType: ActionType;
  status: "success" | "failed";
  message: string;                      // 사용자 노출 메시지 (한국어)
  data?: {
    application?: {                     // MENTORING_APPLY 성공 시
      applySn: number;
      qustnrSn: number;
      mentoringId: string;
      title: string;
      sessionStartedAt?: string;
    };
    calendarInvite?: {                  // MENTORING_APPLY 성공 시 부수 결과
      status: "created" | "skipped" | "failed";
      eventId?: string;                 // mock에서는 UUID
      errorMessage?: string;
    };
  };
  error?: ToolError;                    // status=failed 일 때
  trace_id: string;
};
```

**처리 절차** (백엔드)

1. `actionType` 디스패치 → 해당 tool 매핑
2. `opensoma.mentoring.get`으로 직전 상태 재검증 — 닫힘/마감/이미신청 등 → `409 CONFLICT` + `error.code`
3. `MENTORING_CANCEL` + payload에 `applySn` 없을 시 `applications` 캐시(없으면 채워서) 매핑
4. 실제 tool 호출 (`opensoma.mentoring.apply` / `.cancel`)
5. `MENTORING_APPLY` 성공 시 `calendar.invite.create` (mock) 후속 호출 — 실패해도 신청 롤백 안 함
6. 신청/취소 직후 해당 사용자 `applications` 행 삭제 (다음 조회 시 재채움)

**액션별 페이로드/응답 요약**

| `actionType` | 페이로드 | 성공 응답 `data` |
|---|---|---|
| `MENTORING_APPLY` | `{ mentoringId }` | `{ application, calendarInvite }` |
| `MENTORING_CANCEL` | `{ mentoringId }` 또는 `{ mentoringId, applySn, qustnrSn }` | `{ application: {…cancelled} }` |

### 6.5 HTTP 엔드포인트 — 인증/상태

```
GET /api/v1/auth/status
Headers: X-Soma-Session
Response 200:
{
  "authenticated": true,
  "user": { "somaUserId": "...", "email": "...", "role": "TRAINEE" },
  "integrations": {
    "opensoma": { "status": "connected" },
    "webex":    { "status": "operator_managed" },   // 운영자 토큰이라 사용자별 연동 없음
    "calendar": { "status": "mock" }
  }
}
```

> 페이지 새로고침 후 세션 유효성 확인용. 만료 시 `401` + `X-Soma-Session-Expired: true`.

### 6.6 HTTP 엔드포인트 — 시스템 상태

```
GET /api/v1/system/sync-info
Response 200:
{
  "jobs": {
    "notices_sync":    { "lastRunAt": "...", "lastSuccessAt": "...", "lastError": null },
    "mentorings_sync": { "lastRunAt": "...", "lastSuccessAt": "...", "lastError": null },
    "webex_sync":      { "lastRunAt": "...", "lastSuccessAt": "...", "lastError": "..." }
  }
}
```

> `sync_state` 테이블(§3.1)을 그대로 직렬화. 인증 불필요, 비공개 정보 아님.

### 6.7 에러 응답

표준 형식 `{ code, message, details? }`. (CLAUDE.md `.claude/rules/api.md` 준수.)

| HTTP | code | 의미 | 적용 엔드포인트 |
|---|---|---|---|
| 401 | `SOMA_AUTH_REQUIRED` | 세션 누락/만료 (`X-Soma-Session-Expired: true` 헤더 동봉) | 모두 |
| 403 | `SOMA_AUTH_REJECTED` | OpenSoma가 거부 | 모두 |
| 409 | `ACTION_CONFLICT` | 멘토링 마감/이미 신청 등 상태 충돌 | `/actions/execute` |
| 422 | `INVALID_REQUEST` | 본문 검증 실패 | 모두 |
| 422 | `INVALID_ACTION_TYPE` | 알 수 없는 `actionType` | `/actions/execute` |
| 429 | `RATE_LIMITED` | Solar/Webex rate limit | `/chat` |
| 503 | `UPSTREAM_UNAVAILABLE` | OpenSoma/Webex 다운 | 모두 |

---

## 7. 동기화 정책

### 7.1 잡 정의 (APScheduler)

| 잡 이름 | 주기 | 함수 | 비고 |
|---|---|---|---|
| `notices_sync` | 30분 | `services.notice.run_sync()` | 변경된 공지만 재인덱싱 |
| `mentorings_sync` | 30분 | `services.mentoring.run_sync()` | content_hash 기반 |
| `webex_sync` | 1시간 | `services.webex.run_sync()` | room별 lastSyncedAt 이후만 |

전역 정책:
- 모든 잡은 `sync_state` 테이블에 `last_run_at`/`last_success_at`/`last_error` 갱신.
- 외부 호출은 `tenacity` 로 지수 backoff (3회, 1s/2s/4s).
- pagination은 외부 API 가이드 준수.

### 7.2 공지 동기화 흐름

```
opensoma.notice.list (운영자 토큰)
   → 각 공지 content_hash 비교
   → 변경된 공지만 detail 재조회 + PDF 다운로드 + 텍스트 추출
   → MySQL upsert
   → Qdrant 재인덱싱 (기존 chunk delete-by source_id, 신규 upsert)
```

### 7.3 멘토링 동기화 흐름

```
opensoma.mentoring.list (운영자 토큰)
   → 사라진 mentoring_id → is_active=false
   → 변경된 항목만 detail 조회 → MySQL upsert
   → Qdrant: searchableText = title + description + mentor_name + category + tags 합성 후 임베딩
```

### 7.4 Webex 수집 흐름

운영자 OAuth/Personal Access Token (`OPERATOR_WEBEX_TOKEN`) 기준.

```
GET /rooms?type=group
   → webex_rooms upsert. last_activity_at < last_synced_at 인 룸은 skip
   → 변동 룸만 다음 단계

각 활동 룸:
   GET /messages?roomId=R&max=100
   → 응답은 desc(최신→과거). 최근 24h 윈도우의 메시지를 매 사이클 재조회
     (수정/삭제 부분 보완)
   → 페이지네이션은 `Link: rel=next` 헤더 따라가기 (또는 마지막 메시지 ID로 beforeMessage=)
   → message.created < (now - 24h) 도달 + last_synced_at 이전 메시지면 중단
   → 각 메시지:
       - personEmail.endsWith("@webex.bot") 또는 person_cache.is_bot 인 경우 is_bot_sender=true
       - 30자 미만 텍스트 + 봇 메시지는 임베딩 생략 (RDB 저장은 함, 추적용)
       - sender_key, mentioned_person_keys 모두 HMAC-SHA256 익명화
       - upsert by message_id (있으면 edited_at·text·markdown·html 갱신)
       - 첨부 files[]: URL별로 fetch → PDF/TXT 텍스트 추출 가능 시 추출
   → Qdrant upsert (source_type=WEBEX_MESSAGE, official=false)
   → webex_rooms.last_synced_at = max(last_activity_at, now)
```

**수정/삭제 한계**:
- 정확한 수정/삭제 추적은 Compliance Events API(`spark-compliance:events_read`)가 필요. 운영자 토큰만으로는 불가.
- MVP 부분 보완: 매 사이클 최근 24h 윈도우 재조회 → `edited_at`(Webex `updated`) 변경분 흡수.
- 삭제는 봇 권한 범위에서 감지 어려움. v2에서 Webhook(`messages` resource, `deleted` event) 도입 검토.

> Webex 메시지 요약은 사전 생성하지 않는다. 사용자가 "Webex에서 X 정리해줘" 라고 요청하면 `knowledge.search`로 관련 chunk를 가져와 synthesizer LLM이 응답 생성 시점에 요약한다.

### 7.5 운영자 토큰

| 잡 | 토큰 환경변수 | 만료 시 동작 |
|---|---|---|
| `notices_sync` / `mentorings_sync` | OpenSoma sidecar의 운영자 세션 (sidecar가 `OPERATOR_SOMA_USERNAME` + `OPERATOR_SOMA_PASSWORD`로 자체 로그인 유지) | sidecar가 자동 재로그인 시도. 3회 실패 시 잡 ERROR. |
| `webex_sync` | `OPERATOR_WEBEX_TOKEN` (Personal Access Token 또는 Integration Token) | 401 감지 시 잡 ERROR + 로그. 토큰 갱신은 운영자 수동. |

- 만료 감지 시 잡은 `sync_state.last_error`에 기록하고 다음 사이클 재시도.
- 향후 Slack/Webex 알림 webhook 추가 (v2).

---

## 8. 보안

### 8.1 OpenSoma 세션 격리

- 사용자 ID/PW는 `POST /auth/login` 처리 시점에만 살아있고 sidecar로 위임 후 폐기. **DB·로그 저장 금지.**
- sidecar는 `JSESSIONID`+`csrfToken`을 인메모리 `Map<session_id, cookies>`로만 보관. 디스크 저장 금지, 재시작 시 휘발.
- FastAPI 앱은 `session_id`(우리 발급 핸들)만 알고, OpenSoma 쿠키 원본은 절대 보지 않음.
- 운영자 계정(`OPERATOR_SOMA_USERNAME`/`PASSWORD`)은 sidecar 환경변수로만 주입, FastAPI 앱에는 노출하지 않음.
- `OPERATOR_WEBEX_TOKEN`은 시크릿 매니저에서 로드, 로그·요청 본문에 노출 금지.

### 8.2 발신자 익명화

```python
import hmac, hashlib, os

def anonymize_sender(person_id: str) -> str:
    salt = os.environ["WEBEX_SENDER_SALT"].encode()
    return hmac.new(salt, person_id.encode(), hashlib.sha256).hexdigest()[:32]
```

- `WEBEX_SENDER_SALT` 회전 시 모든 메시지 sender_key 재계산 필요. MVP 회전 안 함.
- 평문 person_id, 이메일은 어디에도 기록하지 않음 (Webex 응답 받자마자 변환).

### 8.3 시크릿 관리

| 환경 | 방식 |
|---|---|
| 로컬 | `.env` (gitignored) → pydantic-settings |
| 실서버 | 컨테이너 환경변수, 값은 시크릿 매니저(AWS SM / GCP SM / Vault 중 인프라 선택)에서 주입 |

`.env` 는 절대 커밋하지 않고 `.env.example` 만 관리.

### 8.4 입력 검증

- 모든 API 요청은 Pydantic 모델로 검증.
- LLM이 생성한 tool 인자는 Pydantic 재검증 후 어댑터에 전달.
- SQL은 SQLAlchemy ORM/parameterized 사용, 문자열 concat 금지.

### 8.5 로그 PII

- 사용자 메시지 본문은 로그에 INFO 레벨로 남기지 않음 (DEBUG에서만, 운영 환경은 INFO 이상).
- 이메일·소마 ID는 `user.{soma_user_id_hash[:8]}` 형태로 마스킹.

---

## 9. 관측성

### 9.1 로깅

- `structlog` JSON 출력.
- 모든 요청에 `trace_id` (UUID) 미들웨어로 발급, ChatMessage에도 포함.
- 표준 필드: `timestamp`, `level`, `trace_id`, `event`, `tool?`, `domain?`, `operation?`, `latency_ms?`, `status?`.

### 9.2 메트릭 (선택, MVP 외)

- `prometheus_client` 로 tool 호출 카운트/레이턴시. MVP는 로그만.

### 9.3 헬스체크

- `GET /healthz` — 프로세스 살아있음.
- `GET /readyz` — MySQL ping + Qdrant ping + Solar ping(선택).

---

## 10. 환경 변수

`.env.example`:

```bash
# App
APP_ENV=local                   # local | dev | prod
APP_PORT=8000
LOG_LEVEL=INFO

# MySQL
MYSQL_HOST=localhost
MYSQL_PORT=3306
MYSQL_USER=soma
MYSQL_PASSWORD=
MYSQL_DATABASE=soma_agent

# Qdrant
QDRANT_HOST=localhost
QDRANT_PORT=6333
QDRANT_COLLECTION=soma_chunks

# Upstage Solar
SOLAR_API_KEY=
# 실측 (2026-05-05): /v1/models로 확인. solar-pro는 latest로 자동 매핑.
SOLAR_LLM_MODEL=solar-pro
# Upstage embedding은 passage(저장용)와 query(검색용)가 분리됨. 둘 다 4096차원.
SOLAR_EMBEDDING_PASSAGE_MODEL=embedding-passage
SOLAR_EMBEDDING_QUERY_MODEL=embedding-query

# OpenSoma Sidecar (FastAPI 앱이 호출하는 내부 URL)
OPENSOMA_SIDECAR_URL=http://opensoma-sidecar:3000

# Webex (운영자 토큰)
OPERATOR_WEBEX_TOKEN=           # OAuth Integration 또는 Personal Access Token (spark:rooms_read spark:messages_read)
WEBEX_SENDER_SALT=              # 32+ chars 랜덤. person_id HMAC 익명화용

# Sync
SYNC_NOTICES_CRON=*/30 * * * *
SYNC_MENTORINGS_CRON=*/30 * * * *
SYNC_WEBEX_CRON=0 * * * *

# Calendar (mock)
CALENDAR_MOCK_FAIL_RATE=0.0     # 0.0~1.0, 테스트용 실패율
```

`opensoma-sidecar/.env.example` (별도 컨테이너):

```bash
# Sidecar
SIDECAR_PORT=3000

# OpenSoma SDK
OPENSOMA_BASE_URL=              # SDK 기본값 사용 시 비워둠
OPERATOR_SOMA_USERNAME=         # 운영자 계정 (스케줄러 잡용)
OPERATOR_SOMA_PASSWORD=         # 노출 금지, 시크릿 매니저에서 주입
```

> 운영자 계정 자격증명은 **sidecar에만** 주입. FastAPI 앱 환경에는 절대 들어가지 않음.

---

## 11. MVP 체크리스트 / 비범위

### 11.1 포함

- [ ] **OpenSoma sidecar PoC** (Bun + TS SDK, HTTP 인터페이스 §3.3 구현)
- [ ] FastAPI 앱 + `POST /api/v1/chat` 엔드포인트
- [ ] `POST /api/v1/auth/login` → sidecar `/sessions` 위임 + `users` upsert
- [ ] `POST /api/v1/auth/logout`
- [ ] `GET /api/v1/auth/status` (세션/연동 상태)
- [ ] `POST /api/v1/actions/execute` — `MENTORING_APPLY` / `MENTORING_CANCEL` 디스패처
- [ ] `GET /api/v1/system/sync-info` (sync_state 직렬화)
- [ ] `X-Soma-Session` 핸들 기반 인증 미들웨어
- [ ] LangGraph 그래프 (router → tool_executor ≤2 → synthesizer) — 채팅 응답에서는 신청/취소 직접 실행 안 함, `ActionProposal`로만 반환
- [ ] Tool 8종 구현 (`knowledge.search`, opensoma 6종, calendar mock)
- [ ] 공지/멘토링/Webex 동기화 잡 (APScheduler)
- [ ] 공지 content HTML → 첨부 anchor 파싱 + PDF 텍스트 추출
- [ ] Webex 메시지 원문 인덱싱 (Link 헤더 페이지네이션, 24h 재스캔)
- [ ] Qdrant 단일 컬렉션 RAG (`source_type` 메타필터)
- [ ] Solar LLM 답변 생성
- [ ] 출처/날짜/공식여부 표시
- [ ] `/actions/execute` 신청/취소 — 직전 `.get` 재검증 + cancel ID 2개 자동 매핑 + calendar mock 후속
- [ ] structlog + trace_id
- [ ] Docker compose (MySQL + Qdrant + FastAPI + opensoma-sidecar)
- [ ] 시연 시나리오 5개 pytest 통합 테스트
- [ ] 아키텍처 의존성 강제 테스트 (AST)

### 11.2 비범위 (v2)

- 실제 Google Calendar 연동
- 개인 DM 수집
- Webex 사전 요약 잡 (`webex_summaries` 테이블 포함)
- Webex Compliance Events API 기반 정확한 수정/삭제 추적
- Webex Webhook 연동 (실시간 메시지)
- 도메인별 RAG tool 분리 (`rag.notice.search` 등) — 통합 `knowledge.search`로 대체됨
- OpenSoma sidecar HA·세션 영속화 (다중 인스턴스, Redis 매핑)
- 멘토링 `category`/`tags` LLM 키워드 추출
- Celery 분산 워커
- 운영자 대시보드
- LangSmith/Langfuse 트레이싱
- 사용자별 알림/푸시
- LLM-as-judge eval 파이프라인
- 자동 의존성 보안 스캔

---

## 12. 미해결 / 확정 필요

| # | 항목 | 액션 |
|---|---|---|
| 1 | ~~Solar LLM/Embedding 모델명 + 차원~~ | ✅ 해결 (2026-05-05): LLM `solar-pro`, embedding `embedding-passage` / `embedding-query`, 차원 4096. `/v1/models` 실측. |
| 2 | OpenSoma 공지 PDF 첨부 처리 | 부분 해결: SDK는 첨부 별도 필드 없음 (#8 PoC 정적 분석). 첨부 있는 공지 만나면 anchor 패턴 확정. #13에서 BeautifulSoup 파싱 |
| 3 | Webex 운영자 토큰으로 그룹 룸 히스토리 조회 가능 여부 | 사내 테스트 룸 1개로 `GET /messages?roomId=...` 실측. 안 되면 Compliance Officer 토큰 필요 — #14 첫 단계 |
| 4 | ~~OpenSoma `applySn` ↔ `qustnrSn` 매핑 시점~~ | ✅ 해결 (#8 PoC): `apply()` 응답 = `Promise<void>`. sidecar가 신청 후 `history()` 한 번 더 호출, `url`의 `qustnrSn=N`로 매칭해 `{apply_sn, qustnr_sn}` 반환 |
| 5 | ~~sidecar `whoami()` 응답 형태~~ | ✅ 해결 (실측): `{userId, userNm, userNo, userGb}`. email은 별도 필드 없음 — `userId`가 곧 이메일. `users` 스키마에 `user_no` 추가 |
| 6 | ~~OpenSoma 일자/시간 문자열 파싱 규칙~~ | ✅ 해결 (실측): notice `createdAt`은 `"YYYY.MM.DD HH:MM:SS"` (점), mentoring은 `"YYYY-MM-DD"` (대시). sessionDate/Time/registrationPeriod는 객체. session은 `{start, end}` 분리 |
| 7 | 운영 시 시크릿 매니저 선택 (AWS SM / GCP SM / Vault) | 인프라 결정 시점에 |
| 8 | OpenSoma 멘토링 `category`/`tags` 필드 부재 | 실측 확인: `type` 한글값 (`"멘토 특강"` 등) 외 별도 카테고리 없음. 분야 검색 품질이 부족하면 v2에서 LLM 키워드 추출 |
| 9 | mentoring `type`·`status` 한글 자유문자열 | 실측 확인: ENUM 강제 안 함, VARCHAR로 자유 흡수 (#10 sync 시 enum 매핑 안 함) |

---

## 13. 시연 시나리오 (pytest 통합 테스트로 고정)

1. **이번 주 주요 공지 요약** — `rag.notice.search` → 출처 포함 응답.
2. **백엔드 멘토링 의미 검색** — `rag.mentoring.search` → `opensoma.mentoring.get` 으로 상태 재확인.
3. **접수 내역 조회** — `opensoma.mentoring.history`.
4. **멘토링 신청 (확인 흐름)** — 첫 턴 `needs_confirmation`, 다음 턴 실행 + (mock) 캘린더 등록.
5. **Webex 주제 검색** — `rag.webex.search` → 비공식 표시 + 공식 공지 부재 안내.

각 시나리오는 `tests/integration/test_chat_flow.py`에 1테스트로 매핑.

---

## 14. 변경 이력

- 2026-05-05: 3차 리비전 — 실측 검증 반영 (#8 PoC). (#TBD)
  - **Solar API 모델 확정**: `solar-pro` (LLM, latest로 자동 매핑), `embedding-passage`/`embedding-query` (저장/검색 분리, 4096차원). 환경변수 `SOLAR_EMBEDDING_MODEL` → `SOLAR_EMBEDDING_PASSAGE_MODEL` + `SOLAR_EMBEDDING_QUERY_MODEL`.
  - **`users` 스키마 정정**: `email` 컬럼 제거, `soma_user_id`가 곧 이메일/username. `user_no`(GUID hex), `user_name`(한글) 컬럼 추가.
  - **`mentorings` 스키마 대폭 수정**: 실측 응답이 객체/boolean이라 단순 문자열 컬럼 분할:
    - `registrationPeriod` → `registration_start_at` / `registration_end_at` (DATETIME)
    - `sessionTime` → `session_start_time` / `session_end_time` (TIME)
    - `attendees` → `attendees_current` / `attendees_max` (INT)
    - `approved` → BOOLEAN
    - `mentoring_type`·`mentoring_status` 한글 자유문자열이라 VARCHAR (ENUM 아님)
  - **일자 포맷 차이 명시**: notice `"YYYY.MM.DD HH:MM:SS"` (점), mentoring `"YYYY-MM-DD"` (대시).
  - **sidecar `apply` 매핑 전략 확정**: `client.mentoring.apply(id)` = `Promise<void>` → sidecar가 신청 직후 `history()` 호출, `url`에서 `qustnrSn=N` 매칭으로 `{apply_sn, qustnr_sn}` 자동 해소.
  - 검증: docker compose up으로 mysql + qdrant + opensoma-sidecar + app 4종 동시 기동 + healthcheck 통과 확인.
- 2026-05-05: 초안 작성. (#TBD)
- 2026-05-05: 1차 리비전. (#TBD)
  - Tool 14개 → 8개로 축소. RAG tool 3개를 `knowledge.search` 단일 tool로 통합 (검색 경로 동일, 메타필터 차이만 존재).
  - `webex_summaries` 테이블 및 `webex_summarize` 잡 제거. 요약은 응답 시점 LLM이 생성.
  - 멘토링 동기화 주기 1시간 → 30분.
  - `domain/`을 `models/`·`schemas/`·`contracts/` 폴더로 분리, 도메인당 모듈로 쪼갬.
  - `services/`를 도메인별 단일 파일(함수 위주)로 정리, 사전 폴더 분할 안 함 (~400줄 임계).
  - 내부 잡(공지/멘토링 크롤, Webex 동기화)은 tool 카탈로그에서 제외.
  - 스키마 잠정 표시: 어댑터 구현 첫 PR에서 OpenSoma·Webex 실제 응답에 맞춰 정렬 예정.
- 2026-05-05: 2차 리비전 — 외부 시스템 실측 반영. (#TBD)
  - **OpenSoma 통합 방식 결정**: 별도 Bun+TS sidecar 컨테이너로 SDK를 wrapping, FastAPI 앱은 sidecar HTTP RPC만 호출 (§3.3 신설). 이유: OpenSoma는 TypeScript SDK + HTML 스크래핑 기반이라 Python에서 직접 활용 불가.
  - **Webex 인증 모델 변경**: 봇 토큰 폐기 → 운영자 OAuth/Personal Access Token (`OPERATOR_WEBEX_TOKEN`). 이유: 봇 토큰은 그룹 룸에서 멘션된 메시지만 읽는 제약.
  - **인증 흐름 재설계**: ID/PW → sidecar 위임 → `session_id` 핸들만 SomaAgent ↔ 클라이언트가 다룸. 쿠키 원본은 sidecar 인메모리에만.
  - **RDB 스키마 전면 재정렬**: OpenSoma TS SDK의 실제 응답 필드(`id`, `author`, `createdAt`, `registrationPeriod`, `sessionDate`/`sessionTime`, `attendees`, `approved`, `applicationStatus`/`approvalStatus`)에 맞춰 컬럼명·타입 갱신. `applications` 테이블 신설(`applySn`+`qustnrSn` 둘 다 보관). `mentoring_applicants` 테이블 신설.
  - **Webex 스키마 보강**: `parent_id`(스레드), `html`, `edited_at`(Webex `updated`), `is_bot_sender`, `mentioned_*`, `files`+`attachments` 분리. `webex_rooms`에 `last_activity_at` 등 추가. ID 컬럼 `VARCHAR(255)`, 시간 `DATETIME(3)`.
  - **Webex 동기화 흐름**: Link 헤더 cursor 페이지네이션, 최근 24h 윈도우 매 사이클 재조회로 수정 감지 부분 보완.
  - **수정/삭제 한계 명시**: Compliance Events API 또는 Webhook 도입은 v2.
  - 환경변수: `OPENSOMA_SIDECAR_URL` 추가, `WEBEX_BOT_TOKEN` → `OPERATOR_WEBEX_TOKEN`. sidecar 전용 `.env.example` 분리(운영자 ID/PW는 sidecar에만).
- 2026-05-05: 3차 리비전 — 액션 실행 분리. (#8)
  - **`POST /api/v1/actions/execute` 엔드포인트 신설** (§6.4). 멘토링 신청/취소는 채팅과 분리해 명시적 액션 디스패처로 처리. 카드 UI 직접 클릭과 채팅 follow-up 두 UX를 동일 경로로 통합.
  - **`ActionProposal` 구조 변경**: `type: string` → `actionType: ActionType` (enum: `MENTORING_APPLY` / `MENTORING_CANCEL`). 채팅 응답에서는 *제안만* 반환, 실제 실행은 프론트가 `/actions/execute`로 위임.
  - **§4.4 액션 실행 정책 재작성**: `needs_confirmation` 2턴 채팅 플로우 폐기. 확인 모달은 프론트 단에서 처리(`requiresConfirmation: true`).
  - **`GET /api/v1/auth/status`** 추가 (§6.5): 페이지 새로고침 후 세션 + 외부 연동 상태 확인.
  - **`GET /api/v1/system/sync-info`** 추가 (§6.6): `sync_state` 직렬화, 동기화 시각 표시용.
  - **신규 에러 코드**: `ACTION_CONFLICT` (409), `INVALID_ACTION_TYPE` (422).
  - 이유: 카드 UI에서 "신청" 버튼을 직접 누르는 UX에 LLM이 불필요하고, 명시적 액션은 idempotent하게 처리 가능. 프론트 측 제안(API 문서 참조) 반영.
