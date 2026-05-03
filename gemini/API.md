1, 2, 3 번 까지는 채팅부분이 아닌, 채팅 이후의 버튼클릭이나, 로그인 부분이라 아마 필수로 필요할 것 같습니다.

다만 4,5 는 채팅 관련 api 이므로, 프론트엔드에서 해줄 수 있는 것은 단순히 사용자 채팅을 보내주는 것이고, 백엔드에서 준 string을 사용자에게 보여주는 것이라, 백엔드 측에서 수정이 필요합니다.

4번 5번은 참고 후 수정해주시길 바랍니다.

디자인 시안 :

https://www.figma.com/make/zkqHaXNzLnYbkYwHc0Hi0D/AI-Chatbot-UI-UX-Design?p=f

### 1. 인증 및 세션 (Authentication)

로그인을 어떤 식으로 구현해주실진 모르겠지만, 정해진 이후에 수정 부탁드립니다

| **기능**           | **메서드** | **엔드포인트**        | **설명**                                                               |
| ------------------ | ---------- | --------------------- | ---------------------------------------------------------------------- |
| **로그인**         | `POST`     | `/api/v1/auth/login`  | OpenSoma 계정으로 로그인 및 세션 생성                                  |
| **로그아웃**       | `POST`     | `/api/v1/auth/logout` | 세션 종료 및 토큰 무효화                                               |
| **연결 상태 확인** | `GET`      | `/api/v1/auth/status` | 현재 로그인된 사용자 정보 및 외부 서비스(Google, Webex) 연동 여부 확인 |

---

### 2. 액션 실행 (Action Execution)

![image.png](attachment:d090d577-7949-4616-bfdb-c566699a1f64:image.png)

실제 신청, 취소를 수행하는 버튼의 API입니다.

### **[POST] /api/v1/actions/execute**

- **Request Body**
  ```json
  {
    "actionType": "MENTORING_APPLY", // MENTORING_APPLY, MENTORING_CANCEL
    "payload": {
      "mentoringId": "M123"
    }
  }
  ```
- **Response Body**
  ```json
  {
    "status": "SUCCESS",
    "message": "멘토링 신청이 완료되었습니다."
  }
  ```

### 3. 시스템 상태 (System Status)

백엔드 스케줄러의 데이터 동기화 상태를 프론트엔드에 표시

| 기능            | 메서드 | 엔드포인트                 | 설명                                      |
| --------------- | ------ | -------------------------- | ----------------------------------------- |
| **동기화 정보** | `GET`  | `/api/v1/system/sync-info` | Webex, 공지사항의 마지막 동기화 시간 반환 |

---

이 밑으로는 수정 부탁

### 4. 채팅 및 에이전트 (Chat & Agent)

핵심 인터페이스인 챗봇 UI와의 통신을 담당합니다.

### **[POST] /api/v1/chat/message**

사용자의 자연어 입력을 받아 에이전트가 분석 후 답변이나 액션을 제안합니다.

- Request Body

```json
{
  "message": "이번 주 백엔드 멘토링 찾아줘",
  "chatSessionId": "string (Optional)"
}
```

- Response Body

```json
{
	 "answer": "이번 주 백엔드와 관련된 멘토링은 2개가 검색되었습니다.",
      "sources": [
        {
          "title": "대규모 트래픽 처리 설계",
          "url": "https://swmaestro.org/...",
          "metoringId": "M123"
          "date": "2026-05-01",
          "time": "14:00 - 15:00"
        }
      ],
      "suggestedActions": [
        {
          "actionType": "MENTORING_APPLY",
          "label": "1번 멘토링 신청하기",
          "payload": { "mentoringId": "M123" }
        }
      ]
}
```

이것도 채팅 외에 버튼식으로 진행할거면 필요하지만, 아직 상세하게는 모르겠습니다.

### 5. 소마 데이터 조회 (Data Retrieval)

| 기능              | 메서드 | 엔드포인트                  | 설명                                            |
| ----------------- | ------ | --------------------------- | ----------------------------------------------- |
| **공지사항 목록** | `GET`  | `/api/v1/notices`           | 최신 공지사항 및 요약 데이터 조회               |
| **멘토링 검색**   | `GET`  | `/api/v1/mentoring/search`  | 키워드/의미 기반 멘토링 검색 (Query Param: `q`) |
| **내 접수 내역**  | `GET`  | `/api/v1/user/applications` | 현재 사용자가 신청한 멘토링 내역 (실시간 조회)  |
| **Webex 요약**    | `GET`  | `/api/v1/webex/summary`     | 특정 키워드나 기간의 Webex 메시지 요약 정보     |
