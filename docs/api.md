# 팜잇(FarmIt) API 명세서

| 항목 | 내용 |
|---|---|
| 버전 | 0.1 (초안) |
| 작성일 | 2026-10-31 |
| 서버 | Django (REST), 세션 인증 |

- **1주차 API**(회원·코드·가격)는 요청·응답까지 확정했다. 나머지는 3절 목록에 주소만 두고 해당 주차에 상세화한다.
- 화면 ID(SCR)는 `docs/screens.md`, 요구사항 ID(REQ)는 `docs/requirements.md`, 테이블은 `docs/erd.md` 기준이다.

---

## 1. 공통 규칙

### 1.1 기본

| 항목 | 규칙 |
|---|---|
| 기본 주소 | `/api` (Vue와 같은 도메인. 개발 중에는 Vite 프록시가 `/api`를 Django로 넘김) |
| 형식 | 요청·응답 모두 JSON, UTF-8. 헤더 `Content-Type: application/json` |
| 이름 규칙 | 필드는 `snake_case`, 주소는 소문자 복수형 명사 (`/api/markets`) |
| 날짜 | `YYYY-MM-DD` (예: `2026-11-02`) |
| 일시 | ISO 8601, 한국 시간 (예: `2026-11-02T09:20:00+09:00`) |
| 가격 | 원/kg, 숫자. 소수 첫째 자리까지 (예: `3507.0`) |
| 물량 | kg, 숫자 |
| 빈 값 | 값이 없으면 `null`. 결과가 없으면 빈 배열 `[]` (오류 아님) |

### 1.2 응답 모양

성공과 실패의 모양을 다르게 해서, 프론트는 HTTP 상태 코드만 보고 어느 쪽인지 판단한다.

**성공**
```json
{
  "data": { },
  "meta": { }
}
```
- `data`: 실제 결과. 단건은 객체, 목록은 배열
- `meta`: 목록의 개수·페이지, 데이터 기준 시각 등 부가 정보. 없으면 생략

**실패**
```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "입력값을 확인해 주세요.",
    "details": {
      "username": ["이미 사용 중인 아이디입니다."]
    }
  }
}
```
- `code`: 프론트가 분기에 쓰는 고정 문자열 (1.5절). **message 문구로 분기하지 않는다.**
- `message`: 사용자에게 그대로 보여 줘도 되는 한국어 문장
- `details`: 입력값 오류일 때만. 필드 이름 → 오류 문장 목록

**예외 — `GET /api/health`** (인증 없음): 서버·DB 상태 확인용이라 `data`로 감싸지 않는다.
정상이면 `200 {"status": "ok"}`, DB에 연결하지 못하면 `503 SERVICE_UNAVAILABLE`(위 실패 모양).

### 1.3 목록·페이지

목록 API 중 길어질 수 있는 것(판매 기록, 알림, 검색 등)은 페이지를 나눈다.

| 쿼리 | 기본값 | 설명 |
|---|---|---|
| `page` | 1 | 페이지 번호 |
| `size` | 20 | 한 페이지 개수 (최대 100) |

```json
"meta": { "page": 1, "size": 20, "total": 57 }
```

### 1.4 인증 (세션)

Django 세션을 쓴다. 로그인하면 서버가 쿠키를 내려 주고, 이후 요청에 브라우저가 자동으로 붙인다.

| 쿠키 | 용도 | 속성 |
|---|---|---|
| `sessionid` | 로그인 상태 | HttpOnly, Secure(배포), SameSite=Lax, 2주 유지 |
| `csrftoken` | 위조 요청 방지 | JS에서 읽을 수 있음 |

**CSRF 규칙**
1. 앱이 처음 뜰 때 `GET /api/auth/csrf`를 한 번 호출해 `csrftoken` 쿠키를 받는다.
2. `POST`·`PATCH`·`DELETE` 요청에는 헤더 `X-CSRFToken: <csrftoken 값>`을 붙인다. (axios 설정 `xsrfCookieName: 'csrftoken'`, `xsrfHeaderName: 'X-CSRFToken'`, `withCredentials: true`)
3. 빠지면 `403 CSRF_FAILED`.

**접근 표시**: 아래 표의 `인증` 열
- `전체`: 로그인 없이 가능
- `회원`: 로그인 필요. 안 되어 있으면 `401 NOT_AUTHENTICATED` → 프론트는 로그인 화면(SCR-001)으로 이동

### 1.5 상태 코드와 오류 코드

**상태 코드는 "무슨 종류의 결과인가", 오류 코드는 "정확히 무엇 때문인가"**를 나타낸다.

#### 성공 (2xx)

| 상태 | 의미 | 쓰는 곳 | 프론트 처리 |
|---|---|---|---|
| `200 OK` | 조회·수정 성공 | GET, PATCH, 로그인 | `data` 사용 |
| `201 Created` | 새로 만들어짐 | 회원가입, 판매 기록 추가 | `data`(만든 것) 사용 |
| `204 No Content` | 성공, 돌려줄 내용 없음 | 로그아웃, 삭제, CSRF 발급 | 본문 없음 |

#### 사용자 쪽 문제 (4xx) — 요청을 고치면 해결됨

| 상태 | 오류 코드 | 의미 | 예시 | 프론트 처리 |
|---|---|---|---|---|
| `400` | `VALIDATION_ERROR` | 입력값이 형식·규칙에 안 맞음 | 비밀번호 8자 미만, 날짜 형식 틀림, `from`이 `to`보다 늦음 | `details`를 각 입력칸 아래에 표시 |
| `400` | `INVALID_PARAMETER` | 쿼리 값이 허용 범위 밖 | `unit=year`, `size=500` | 개발 중 버그로 보고 수정 |
| `401` | `NOT_AUTHENTICATED` | 로그인 안 됨 또는 세션 만료 | 회원 API를 비로그인으로 호출 | 로그인 화면으로 이동 |
| `401` | `INVALID_CREDENTIALS` | 아이디·비밀번호 불일치 | 로그인 실패 | "아이디 또는 비밀번호가 맞지 않습니다" (어느 쪽이 틀렸는지 알려 주지 않음) |
| `403` | `CSRF_FAILED` | CSRF 토큰 없음·불일치 | 헤더 누락 | `/api/auth/csrf` 다시 호출 후 재시도 |
| `403` | `FORBIDDEN` | 로그인은 했지만 권한 없음 | 남의 판매 기록 수정 | 안내 문구 |
| `404` | `NOT_FOUND` | 대상이 없음 | 없는 시장 코드, 지워진 판매 기록 | 안내 문구 또는 오류 화면(SCR-017) |
| `405` | `METHOD_NOT_ALLOWED` | 그 주소에서 허용하지 않는 HTTP 메서드 | 로그인 주소를 GET으로 호출 | 개발 중 버그로 보고 수정 |
| `409` | `DUPLICATE_USERNAME` | 이미 있는 아이디 | 회원가입 | 아이디 칸에 표시 |
| `409` | `CONFLICT` | 이미 처리된 상태와 충돌 | 같은 기록 두 번 저장 | 목록 새로고침 |
| `415` | `UNSUPPORTED_MEDIA_TYPE` | 본문이 JSON이 아님 | `Content-Type`이 `text/plain` | 개발 중 버그로 보고 수정 |
| `429` | `TOO_MANY_LOGIN_ATTEMPTS` | 로그인 5회 연속 실패 → 10분 잠금 | 로그인 | `retry_after_seconds`만큼 기다리라고 안내 |
| `429` | `CHAT_DAILY_LIMIT` | 오늘 채팅 질문 20회 초과 (REQ-NFR-008) | 채팅·증상 진단 | "내일 다시 이용" 안내 (SCR-017) |
| `429` | `RATE_LIMITED` | 짧은 시간에 요청이 너무 많음 | 같은 API 연속 호출 | `retry_after_seconds` 후 재시도 |

#### 서버 쪽 문제 (5xx) — 요청은 맞고, 우리 쪽 또는 외부 문제

| 상태 | 오류 코드 | 의미 | 예시 | 프론트 처리 |
|---|---|---|---|---|
| `500` | `INTERNAL_ERROR` | 예상하지 못한 서버 오류 | 코드 버그 | "잠시 후 다시 시도" + 서버 로그 확인 |
| `502` | `UPSTREAM_ERROR` | 외부 서비스가 오류를 돌려줌 | LLM API 오류 | "잠시 후 다시 시도" |
| `503` | `DATA_NOT_READY` | 필요한 데이터가 아직 준비되지 않음 | 이번 주 예측 작업 전, 오늘 경매 수집 전 | "데이터 준비 중" 안내 (일시적) |
| `503` | `SERVICE_UNAVAILABLE` | 점검·과부하 | 배포 중 | 점검 안내 |
| `504` | `UPSTREAM_TIMEOUT` | 외부 서비스가 제때 응답하지 않음 | LLM 응답 지연 | 재시도 버튼 |

#### 헷갈리기 쉬운 구분

| 상황 | 응답 | 이유 |
|---|---|---|
| 조건에 맞는 가격 데이터가 없음 (그날 거래 없음) | `200` + `data: []` | 정상적인 "결과 없음" |
| 품목 ID 자체가 없음 | `404 NOT_FOUND` | 대상이 존재하지 않음 |
| 예측 대상이 아닌 품목(`is_forecast` false)으로 예측 요청 | `200` + `forecast_available: false` | 정상 동작. 시장 비교만 제공 (REQ-REC-003) |
| 이번 주 예측 작업이 아직 안 돎 | `503 DATA_NOT_READY` | 원래 있어야 하는데 일시적으로 없음 |
| 로그인 안 함 | `401` | 누구인지 모름 |
| 로그인했지만 남의 데이터 | `403` (또는 존재를 숨기려면 `404`) | 누구인지 알지만 권한 없음. 판매 기록은 `404`로 응답해 존재 여부를 숨긴다 |
| 형식은 맞는데 값이 틀림 (`from > to`) | `400 VALIDATION_ERROR` | 사용자가 고칠 수 있음 |

표에 없는 4xx(예: 406)는 원래 상태 코드를 유지하고 오류 코드는 `VALIDATION_ERROR`로 보낸다.

`429` 응답에는 `details.retry_after_seconds`를 넣고, HTTP 헤더 `Retry-After`도 같이 보낸다.

---

## 2. 1주차 API

### 2.1 인증·회원

#### `GET /api/auth/csrf` — CSRF 쿠키 발급
| 인증 | 화면 | REQ |
|---|---|---|
| 전체 | 앱 시작 시 | REQ-NFR-004 |

- 응답: `204` + `Set-Cookie: csrftoken=...`

---

#### `GET /api/auth/check-username` — 아이디 중복 확인
| 인증 | 화면 | REQ |
|---|---|---|
| 전체 | SCR-002 | REQ-USR-001 |

| 쿼리 | 필수 | 설명 |
|---|---|---|
| `username` | O | 확인할 아이디 |

**200**
```json
{ "data": { "username": "farmer01", "available": false } }
```
- 사용 중이어도 오류가 아니라 `available: false`로 응답한다.
- 아이디 규칙 위반이면 `400 VALIDATION_ERROR`

---

#### `POST /api/auth/signup` — 회원가입
| 인증 | 화면 | REQ |
|---|---|---|
| 전체 | SCR-002 | REQ-USR-001, 003, REQ-NFR-006 |

**요청**
```json
{
  "username": "farmer01",
  "password": "apple2026!",
  "password_confirm": "apple2026!",
  "sido": "충청북도",
  "sigungu": "충주시",
  "interest_item_ids": [1, 7],
  "agree_terms": true,
  "agree_privacy": true
}
```

| 필드 | 필수 | 규칙 |
|---|---|---|
| `username` | O | 영문 소문자·숫자 4~20자 |
| `password` | O | 8자 이상, 영문·숫자 포함 |
| `password_confirm` | O | `password`와 같아야 함 |
| `sido`, `sigungu` | O | 시군 단위까지 |
| `interest_item_ids` | X | 품목 ID 목록 (최대 5개) |
| `agree_terms`, `agree_privacy` | O | 둘 다 `true` |

**201** — 가입과 동시에 로그인 처리 (`sessionid` 쿠키 발급)
```json
{
  "data": {
    "id": 12,
    "username": "farmer01",
    "sido": "충청북도",
    "sigungu": "충주시",
    "interest_items": [
      { "item_id": 1, "name": "사과" },
      { "item_id": 7, "name": "배" }
    ]
  }
}
```

**오류**: `400 VALIDATION_ERROR`(규칙 위반·약관 미동의·없는 품목 ID), `409 DUPLICATE_USERNAME`

---

#### `POST /api/auth/login` — 로그인
| 인증 | 화면 | REQ |
|---|---|---|
| 전체 | SCR-001 | REQ-USR-002 |

**요청**
```json
{ "username": "farmer01", "password": "apple2026!" }
```

**200** — `sessionid` 쿠키 발급. `data`는 `GET /api/users/me`와 같은 모양

**오류**
- `401 INVALID_CREDENTIALS`
- `429 TOO_MANY_LOGIN_ATTEMPTS` — 같은 아이디로 5회 연속 실패 시 10분
```json
{
  "error": {
    "code": "TOO_MANY_LOGIN_ATTEMPTS",
    "message": "로그인 시도가 너무 많습니다. 10분 후 다시 시도해 주세요.",
    "details": { "retry_after_seconds": 600 }
  }
}
```

---

#### `POST /api/auth/logout` — 로그아웃
| 인증 | 화면 | REQ |
|---|---|---|
| 회원 | SCR-015 | REQ-USR-002 |

- 응답: `204`. 세션 삭제
- 이미 로그아웃 상태여도 `204` (결과가 같으므로 오류로 보지 않음)

---

#### `GET /api/users/me` — 내 정보 (로그인 상태 확인 겸용)
| 인증 | 화면 | REQ |
|---|---|---|
| 회원 | SCR-003, SCR-015, 앱 시작 시 | REQ-USR-003 |

**200**
```json
{
  "data": {
    "id": 12,
    "username": "farmer01",
    "sido": "충청북도",
    "sigungu": "충주시",
    "interest_items": [{ "item_id": 1, "name": "사과" }],
    "transport_cost_per_km": 1500,
    "storage_cost_per_week": 3000,
    "loss_rate": 0.0,
    "chat_remaining_today": 20
  }
}
```
- 앱 시작 시 호출해서 `200`이면 로그인 상태, `401`이면 비로그인으로 판단한다.

---

#### `PATCH /api/users/me` — 내 정보 수정
| 인증 | 화면 | REQ |
|---|---|---|
| 회원 | SCR-015 | REQ-USR-003 |

**요청** — 바꿀 필드만 보낸다
```json
{
  "sigungu": "청주시",
  "interest_item_ids": [1],
  "transport_cost_per_km": 1800,
  "loss_rate": 2.5
}
```

| 필드 | 규칙 |
|---|---|
| `transport_cost_per_km`, `storage_cost_per_week` | 0 이상 정수 |
| `loss_rate` | 0 이상 100 미만 (%) |

**200** — 수정 후의 내 정보 (`GET /api/users/me`와 같은 모양)

**오류**: `400 VALIDATION_ERROR`. 아이디(`username`)는 바꿀 수 없다.

---

#### `DELETE /api/users/me` — 회원 탈퇴
| 인증 | 화면 | REQ |
|---|---|---|
| 회원 | SCR-015 | REQ-USR-004 |

**요청** — 실수 방지를 위해 비밀번호를 다시 받는다
```json
{ "password": "apple2026!" }
```

**204** — 계정과 개인 데이터(프로필, 관심 품목, 판매 기록, 알림, 채팅)를 모두 삭제하고 세션 종료

**오류**: `401 INVALID_CREDENTIALS`(비밀번호 불일치)

---

### 2.2 코드

#### `GET /api/markets` — 시장 목록
| 인증 | 화면 | REQ |
|---|---|---|
| 전체 | SCR-004, 005, 007 | REQ-PRC-001, REQ-NFR-010 |

| 쿼리 | 기본값 | 설명 |
|---|---|---|
| `q` | - | 이름 일부로 검색 (예: `천`). 일치하는 시장이 없으면 `200` + `data: []` |
| `collect` | `true` | `true`면 수집 대상 시장만 (4개 + 가락), `false`면 전체 33곳. 그 밖의 값은 `400 INVALID_PARAMETER` |

**200**
```json
{
  "data": [
    { "market_id": "250001", "name": "대전오정", "sido": "대전광역시", "is_reference": false },
    { "market_id": "250003", "name": "대전노은", "sido": "대전광역시", "is_reference": false },
    { "market_id": "340101", "name": "천안", "sido": "충청남도", "is_reference": false },
    { "market_id": "330101", "name": "청주", "sido": "충청북도", "is_reference": false },
    { "market_id": "110001", "name": "서울가락", "sido": "서울특별시", "is_reference": true }
  ]
}
```

---

#### `GET /api/items` — 품목 목록·검색
| 인증 | 화면 | REQ |
|---|---|---|
| 전체 | SCR-002, 004, 005 | REQ-SRC-001 |

| 쿼리 | 기본값 | 설명 |
|---|---|---|
| `q` | - | 이름 일부로 검색 (예: `사`) |
| `forecast` | - | `true`면 가격 예측 제공 품목만 |

`forecast`가 `true`·`false`가 아니면 `400 INVALID_PARAMETER`. 일치하는 품목이 없으면 `200` + `data: []`.

**200**
```json
{
  "data": [
    { "item_id": 1, "name": "사과", "category": "과일", "is_storable": true, "is_forecast": true }
  ]
}
```

---

### 2.3 가격

#### `GET /api/prices/daily` — 기간별 가격 추이 (정산 확정)
| 인증 | 화면 | REQ |
|---|---|---|
| 전체 | SCR-004 | REQ-PRC-001, 002, 005 |

| 쿼리 | 필수 | 기본값 | 설명 |
|---|---|---|---|
| `item_id` | O | | 품목 |
| `market_id` | O | | 시장 |
| `from` | X | 오늘 − 90일 | 시작일 |
| `to` | X | 어제 | 종료일 (정산은 다음 날 반영) |
| `unit` | X | `day` | `day`·`week`·`month` |
| `grade` | X | `ALL` | 등급. `ALL`은 전 등급 물량가중 평균 |
| `compare_last_year` | X | `false` | `true`면 전년 같은 기간 값을 함께 |

- 기간 제한: `unit=day`는 최대 1년, `week`·`month`는 최대 5년 (일수가 아니라 연으로 센다. `from`에 N년을 더한 날짜까지 허용). 넘으면 `400 VALIDATION_ERROR`

**200**
```json
{
  "data": [
    {
      "period": "2026-10-26",
      "avg_price": 3507.0,
      "min_price": 2100.0,
      "max_price": 5200.0,
      "volume_kg": 18420.0,
      "last_year_avg_price": 3980.0
    }
  ],
  "meta": {
    "item_id": 1,
    "market_id": "250001",
    "unit": "week",
    "grade": "ALL",
    "price_unit": "원/kg",
    "last_updated": "2026-11-01T06:10:00+09:00"
  }
}
```
- `period`: 일 단위는 그날, 주 단위는 그 주 월요일, 월 단위는 `YYYY-MM`
- 거래가 없는 날·주는 행을 만들지 않는다 (차트에서 끊어 표시)
- `last_year_avg_price`는 `compare_last_year=true`일 때만 포함
- `last_updated`: 마지막 정산 수집 시각 (`collect_log` 기준)

- 주·월 단위 `avg_price`는 물량가중 평균(Σ가격×물량 / Σ물량)이다. 전년 비교는 일 단위는 1년 전, 주 단위는 52주 전(같은 요일), 월 단위는 12개월 전과 맞추고, 전년 데이터가 없으면 `null`이다.
- `from`·`to`는 `YYYY-MM-DD`만 받고 2000-01-01~2100-12-31 범위여야 한다 (밖이면 `400 VALIDATION_ERROR`). 둘 다 그날을 포함한다.
- 가격은 소수 첫째 자리로 반올림해 돌려준다. `from`이 주·월 중간이면 첫 행의 `period`는 그 주 월요일·그 달 1일이고 집계는 `from` 이후 날짜만으로 한다.

**오류**: `404 NOT_FOUND`(없는 품목·시장), `400 VALIDATION_ERROR`(필수 값 없음, 날짜 형식, `from > to`, 기간 초과), `400 INVALID_PARAMETER`(`unit`·`compare_last_year` 값이 허용 범위 밖)

---

#### `GET /api/prices/compare` — 시장 간 비교
| 인증 | 화면 | REQ |
|---|---|---|
| 전체 | SCR-004 | REQ-PRC-003 |

| 쿼리 | 필수 | 기본값 | 설명 |
|---|---|---|---|
| `item_id` | O | | 품목 |
| `date` | X | 가장 최근 정산일 | 비교할 날짜 |
| `grade` | X | `ALL` | 등급 |

**200**
```json
{
  "data": [
    { "market_id": "250001", "market_name": "대전오정", "avg_price": 3507.0, "volume_kg": 2310.0 },
    { "market_id": "250003", "market_name": "대전노은", "avg_price": 3763.0, "volume_kg": 1820.0 },
    { "market_id": "340101", "market_name": "천안", "avg_price": null, "volume_kg": 0 },
    { "market_id": "330101", "market_name": "청주", "avg_price": 3673.0, "volume_kg": 2950.0 }
  ],
  "meta": { "item_id": 1, "date": "2026-10-30", "grade": "ALL", "price_unit": "원/kg" }
}
```
- 수집 대상 시장은 거래가 없어도 행을 넣고 `avg_price: null`로 둔다 (화면에서 "거래 없음" 표시).
- 참고 시장(가락)은 포함하지 않는다.
- `date`를 생략했는데 그 품목·등급의 정산 데이터가 하나도 없으면 `200`, 모든 시장 `avg_price: null`, `meta.date: null`이다.

**오류**: `404 NOT_FOUND`(없는 품목), `400 VALIDATION_ERROR`(`item_id` 필수·숫자, `date` 형식)

---

#### `GET /api/prices/realtime` — 당일 경매 가격
| 인증 | 화면 | REQ |
|---|---|---|
| 전체 | SCR-003, SCR-004 | REQ-PRC-004, REQ-NFR-003 |

| 쿼리 | 필수 | 설명 |
|---|---|---|
| `item_id` | O | 품목 |
| `market_id` | X | 없으면 수집 대상 4개 시장 모두 |

**200**
```json
{
  "data": [
    {
      "market_id": "250001",
      "market_name": "대전오정",
      "trade_date": "2026-11-02",
      "avg_price": 3420.0,
      "min_price": 1900.0,
      "max_price": 5100.0,
      "volume_kg": 1240.0,
      "trade_count": 37,
      "last_auction_at": "2026-11-02T08:42:00+09:00",
      "status": "live"
    }
  ],
  "meta": { "collected_at": "2026-11-02T09:05:00+09:00", "price_unit": "원/kg" }
}
```

| `status` | 의미 | 화면 표시 |
|---|---|---|
| `live` | 경매 시간(한국 시간 12시 전), 수집 중 | "경매 중 · 09:05 기준" |
| `closed` | 오늘 경매 종료(12시 이후), 정산 전 | "오늘 경매 종료 · 확정 전" |
| `no_trade` | 오늘 이 시장에 거래 없음 | "오늘 거래 없음" |

- Flink가 채우는 `realtime_price`에서 읽는다 (K27). `trade_date`는 **정산일자**라 전날 오후 경매분도 포함한다 (`settle_price`와 같은 기준).
- `live`/`closed` 경계는 12시: 경매는 11시쯤 끝나지만 API 반영이 약 20분 늦어 수집기가 12시까지 돈다.
- `market_id`가 없으면 수집 대상 시장(`market.is_collect`)을 모두 돌려주고, 거래가 없는 시장도 `status: "no_trade"`, 가격 `null`, `volume_kg: 0`, `trade_count: 0`으로 넣는다. 참고 시장(가락)은 넣지 않는다.
- `meta.collected_at`: 오늘 정산일자로 끝난 마지막 수집 시각 (`collect_log`의 `at_auction`, 실패 제외).
- 다음 날 정산이 들어오면 확정 가격은 `/api/prices/daily`에서 본다 (REQ-PRC-004). 이 API에는 "확정" 상태가 없다.

**오류**: `400 VALIDATION_ERROR`(`item_id` 없음·숫자 아님), `404 NOT_FOUND`(없는 품목·시장), `503 DATA_NOT_READY`(오늘 정산일자로 끝난 수집이 아직 없음)

### 2.4 알림 (회원 전용)

세 API 모두 로그인 필요(`401 NOT_AUTHENTICATED`). **남의 알림은 403이 아니라 `404 NOT_FOUND`**.

#### `GET /api/alerts` — 알림 목록
쿼리: `unread=true`(안 읽은 것만, 기본 false), `page`, `size`(1.3절). 최신 발생순. 값이 잘못되면 `400 INVALID_PARAMETER`.
```json
{ "data": [ { "id": 7, "event_type": "WARNING", "title": "가평군 한파주의보 발표",
  "sido": "경기도", "sigungu": "가평군", "occurred_at": "2026-11-06T11:00:00+09:00",
  "created_at": "2026-11-06T11:00:05+09:00", "read_at": null, "is_read": false } ],
  "meta": { "page": 1, "size": 20, "total": 1 } }
```

#### `GET /api/alerts/{id}` — 알림 상세 + 대응 체크리스트
목록 항목의 필드에 `item_id`, `detail`(상황별 상세 JSON), `source_url`(출처 링크), `checklist`를 더한다. 상세를 열기만 해서는 읽음 처리되지 않는다.
`checklist`: `{"before": [사전 대비...], "after": [사후 조치...], "sources": [{"name": "일반 안내(기관 원문 대조 전). ..."}]}`. 체크리스트가 없는 종류(수입량 급증·정부 발표)는 `null`. 특보 유형(한파·호우·태풍 등)별 내용은 코드 상수(`alerts/checklists.py`)이고, 모르는 유형은 일반 체크리스트.
**오류**: `404 NOT_FOUND`

#### `PATCH /api/alerts/{id}/read` — 읽음 처리
본문 없음. `200`, `data`는 목록 항목과 같은 모양(`read_at` 채워짐). 이미 읽은 알림은 처음 읽은 시각을 유지한다.
**오류**: `404 NOT_FOUND`

---

### 2.6 판매 기록 (회원 전용)

네 API 모두 로그인 필요(`401 NOT_AUTHENTICATED`), 쓰기는 CSRF 필요. **남의 기록은 403이 아니라 `404 NOT_FOUND`**.
| 화면 | REQ |
|---|---|
| SCR-006, SCR-007 | REQ-SAL-001, 002 |

기록 모양(목록·생성·수정 응답 공통):
```json
{ "id": 3, "sale_date": "2026-11-10", "market_id": "250001", "market_name": "대전오정",
  "item_id": 1, "item_name": "사과", "grade": "ALL", "volume_kg": 100.0, "amount_won": 330000,
  "unit_price": 3300.0, "avg_price": 3000.0, "vs_avg_pct": 10.0, "created_at": "2026-11-15T10:00:00+09:00" }
```
- `unit_price` = `amount_won / volume_kg` (원/kg, 소수 첫째 자리).
- `avg_price`: 같은 날짜·시장·품목·등급의 정산 확정 평균가(`settle_price`). 없으면 `null`.
- `vs_avg_pct` = `(unit_price / avg_price − 1) × 100`, 소수 첫째 자리. `avg_price`가 없거나 0이면 `null` ("비교할 평균 없음"으로 표시). 반올림 전 단가로 계산한다. 정산은 다음 날 반영되므로 어제·오늘 판매는 `null`일 수 있다. 조회할 때마다 계산하므로 나중에 정산이 들어오면 값이 채워진다.

#### `GET /api/sales` — 내 판매 기록 목록
쿼리: `from`·`to`(YYYY-MM-DD, 기본 전체), `page`, `size`(1.3절). 판매일 최신순.
`meta`: `page`, `size`, `total`, `total_volume_kg`, `total_amount_won` (합계는 페이지가 아니라 **기간 전체**).
**오류**: `400 VALIDATION_ERROR`(날짜 형식, `from` > `to`), `400 INVALID_PARAMETER`(`page`·`size`)

#### `POST /api/sales` — 판매 기록 추가
| 본문 | 필수 | 설명 |
|---|---|---|
| `sale_date` | O | 판매일. 2000-01-01 ~ 오늘(KST) |
| `market_id` | O | 시장 코드 (`/api/markets`) |
| `item_id` | O | 품목 |
| `grade` | X | 기본 `ALL` (최대 10자) |
| `volume_kg` | O | 0.1 이상, 소수 첫째 자리까지 (정수 11자리 이하) |
| `amount_won` | O | 받은 총액(원), 0 이상 정수 (최대 10^13) |

**201** `data` = 기록 모양. **오류**: `400 VALIDATION_ERROR`(`details`에 필드별)

#### `PATCH /api/sales/{id}` — 수정
위 본문의 일부만 보내도 된다. **200** `data` = 기록 모양. **오류**: `400`, `404`

#### `DELETE /api/sales/{id}` — 삭제
**204**. **오류**: `404`

---

## 3. 2주차 이후 API (주소 목록)

상세는 해당 주차 시작 전에 이 문서에 추가한다.

| 메서드 | 주소 | 인증 | 설명 | 화면 | REQ | 주차 |
|---|---|---|---|---|---|---|
| GET | `/api/sales` | 회원 | **(2.6에 상세)** 판매 기록 목록 (기간 필터, 평균 대비 %) | SCR-006 | REQ-SAL-001, 002 | 2 |
| POST | `/api/sales` | 회원 | **(2.6에 상세)** 판매 기록 추가 | SCR-007 | REQ-SAL-001 | 2 |
| PATCH | `/api/sales/{id}` | 회원 | **(2.6에 상세)** 판매 기록 수정 | SCR-007 | REQ-SAL-001 | 2 |
| DELETE | `/api/sales/{id}` | 회원 | **(2.6에 상세)** 판매 기록 삭제 | SCR-007 | REQ-SAL-001 | 2 |
| GET | `/api/forecasts` | 전체 | 주간 예측 (item_id, market_id) — 예측값·80% 구간·명절 주의 | SCR-003, 005 | REQ-PRD-001~003 | 2 |
| POST | `/api/recommendations` | 회원 | 판매 추천 계산 (품목·물량·시기·비용) | SCR-005 | REQ-REC-001~006 | 2 |
| GET | `/api/alerts` | 회원 | 알림 목록 (`unread=true` 필터) | SCR-003, 008 | REQ-ALT-003 | 3 |
| GET | `/api/alerts/{id}` | 회원 | 알림 상세 + 대응 체크리스트 | SCR-009 | REQ-ALT-002 | 3 |
| PATCH | `/api/alerts/{id}/read` | 회원 | 읽음 처리 | SCR-009 | REQ-ALT-003 | 3 |
| GET | `/api/cases` | 전체 | 과거 사례 (item_id, event_type) | SCR-010 | REQ-HIS-001, 002 | 3 |
| GET | `/api/search` | 전체 | 통합 검색 (`type`: item·market·press) | SCR-014 | REQ-SRC-001, 002 | 3 |
| GET | `/api/notices` | 전체 | 시장 공지 (선택) | SCR-014 | REQ-SRC-003 | 3 |
| POST | `/api/chat/messages` | 회원 | 질문 보내기 → 스트리밍 응답(SSE: 진행 상태 → 답변 → 출처) | SCR-011 | REQ-CHT-001~007 | 4 |
| GET | `/api/chat/sessions` | 회원 | 이전 대화 목록 | SCR-011 | REQ-CHT-008 | 4 |
| GET | `/api/chat/sessions/{id}` | 회원 | 대화 내용 | SCR-011 | REQ-CHT-008 | 4 |
| GET | `/api/farming/monthly` | 전체 | 이번 달 할 일 (item_id, month) | SCR-003, 012 | REQ-RAG-002 | 4 |
| GET | `/api/farming/calendar` | 전체 | 연간 작업 일정 | SCR-012 | REQ-RAG-003 | 4 |
| GET | `/api/farming/summary` | 전체 | 품목 요약 | SCR-012 | REQ-RAG-006 | 4 |
| GET | `/api/farming/guide` | 전체 | 처음 할 일 요약 (선택) | SCR-012 | REQ-RAG-004 | 4 |
| POST | `/api/farming/diagnose` | 회원 | 증상 진단 (채팅 한도에 포함) | SCR-013 | REQ-RAG-001 | 4 |
| GET | `/api/prices/retail` | 전체 | KAMIS 도·소매 참고 가격 (선택) | SCR-004 | REQ-PRC-006 | 12월 |
| POST | `/api/sales/ocr` | 회원 | 정산서 사진 → 입력값 추출 (선택) | SCR-007 | REQ-SAL-004 | 12월 |
| POST | `/api/price-alerts` | 회원 | 목표가격 알림 설정 (선택) | SCR-008 | REQ-ALT-007 | 12월 |

---

## 4. 프론트 연결 메모 (김기현)

- axios 기본 설정: `baseURL: '/api'`, `withCredentials: true`, `xsrfCookieName: 'csrftoken'`, `xsrfHeaderName: 'X-CSRFToken'`
- 앱 시작: `GET /api/auth/csrf` → `GET /api/users/me` (200 = 로그인, 401 = 비로그인)
- 응답 인터셉터에서 상태 코드로 공통 처리
  - `401` → 로그인 화면
  - `403 CSRF_FAILED` → csrf 재발급 후 한 번 재시도
  - `429` → `retry_after_seconds` 안내
  - `5xx` → "잠시 후 다시 시도" 토스트
  - `400 VALIDATION_ERROR` → 화면에서 `details`를 입력칸별로 표시
