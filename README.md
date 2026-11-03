# 팜잇 (FarmIt)

농사를 막 시작한 농업인 곁에서 재배부터 판매까지 판단을 돕는 AI 농사 도우미.
SSAFY 관통 프로젝트 · 양정호, 김기현 · 2026-10-19 ~ 2026-12-24

## 문서

| 문서 | 내용 |
|---|---|
| [docs/requirements.md](docs/requirements.md) | 요구사항 정의서 |
| [docs/screens.md](docs/screens.md) | 화면 목록 |
| [docs/erd.md](docs/erd.md) | ERD |
| [docs/api.md](docs/api.md) | API 명세서 |

## 폴더 구조

```
backend/       Django API 서버
frontend/      Vue 웹
collectors/    Open API 수집기 (aT, 기상청, KOSIS, 관세청, NCPMS 등)
streaming/     Kafka 프로듀서, Flink 작업 (실시간 경로)
batch/         Spark 작업, Airflow DAG (배치 경로)
ml/            가격 예측 모델, MLflow
rag/           재배·병해충 문서 수집, 색인, 검색
infra/         docker-compose, Nginx 등 실행 환경
docs/          요구사항, 화면, ERD, API 문서
```

## 실행

Docker와 Docker Compose(v2)가 필요하다. 명령은 모두 **레포 루트**에서 실행한다.

```bash
# 1. 환경 변수 파일 만들기 → 빈 값 중 아래 3개는 반드시 채운다
cp .env.example .env
#    MYSQL_PASSWORD, MYSQL_ROOT_PASSWORD : 아무 비밀번호
#    DJANGO_SECRET_KEY                   : python3 -c "import secrets; print(secrets.token_urlsafe(50))"
#    외부 API 키는 해당 기능을 만들 때 채운다

# 2. 실행 (처음 또는 requirements.txt·Dockerfile을 바꿨을 때 --build)
docker compose -f infra/docker-compose.yml up --build

# 3. 확인 → {"status": "ok"}
curl localhost:8000/api/health
```

| 서비스 | 주소 | 비고 |
|---|---|---|
| backend (Django) | http://localhost:8000 | `backend/`가 마운트되어 코드 저장 시 자동 재시작 |
| mysql 8.4 | localhost:**3307** | DB 도구로 접속할 때. 컨테이너끼리는 `mysql:3306` |

자주 쓰는 명령

```bash
docker compose -f infra/docker-compose.yml logs -f backend                    # 로그 보기
docker compose -f infra/docker-compose.yml exec backend python manage.py test # 테스트 (test_farmit DB 자동 생성·삭제)
docker compose -f infra/docker-compose.yml exec backend python manage.py makemigrations
docker compose -f infra/docker-compose.yml down                               # 종료 (DB 데이터 유지)
docker compose -f infra/docker-compose.yml down -v                            # 종료 + DB 데이터 삭제
```

- `.env`의 `MYSQL_*` 값과 `infra/mysql/init/` 스크립트는 **DB 볼륨이 비어 있을 때(첫 실행)만** 적용된다. 바꾼 뒤에는 `down -v`로 볼륨을 지우고 다시 띄운다.
- backend는 시작할 때 `migrate`를 먼저 실행한다.

## 개발 규칙

- **시간:** DB에는 UTC로 저장하고(Django `USE_TZ=True`, MySQL `default-time-zone=+00:00`), 화면·API 응답에서 Asia/Seoul로 바꿔 보여 준다. 수집기·배치도 UTC로 저장한다.

## 브랜치

```
master    배포용. 발표·배포 시점에만 develop에서 합친다
develop   개발 통합. 모든 작업은 여기로 합친다
feature/  기능 작업 (develop에서 만들어 develop으로 MR)
```

- 브랜치 이름: `종류/영역-내용` (영문 소문자, 하이픈)
  - 종류: `feature`(기능) · `fix`(버그) · `docs`(문서) · `chore`(설정·환경)
  - 영역: `be`(백엔드) · `fe`(프론트) · `data`(수집·배치·스트리밍) · `ml` · `rag` · `infra`
  - 예: `feature/be-price-api`, `feature/fe-login`, `fix/data-settle-date`, `chore/infra-compose`
- 작업 순서
  1. `git checkout develop && git pull`
  2. `git checkout -b feature/be-price-api`
  3. 작업 · 커밋 · `git push -u origin feature/be-price-api`
  4. GitLab에서 develop으로 MR 생성
  5. 합친 뒤 브랜치 삭제

## 커밋 메시지

```
종류: 내용 (REQ-ID)
```

| 종류 | 언제 |
|---|---|
| `feat` | 새 기능 |
| `fix` | 버그 수정 |
| `docs` | 문서 |
| `refactor` | 동작은 같고 코드 구조만 변경 |
| `test` | 테스트 |
| `chore` | 설정, 패키지, 빌드, Docker |

예: `feat: 기간별 가격 조회 API (REQ-PRC-001)`, `fix: 정산 수집 날짜 형식 수정 (REQ-COL-001)`

## MR 규칙

1. `develop`·`master`에 직접 푸시하지 않고 MR로만 합친다.
2. MR 제목에 요구사항 ID를 넣는다. 예: `[REQ-PRC-001] 기간별 가격 API`
3. MR 설명은 템플릿(무엇을 / 왜 / 확인 방법)을 채운다.
4. 상대방이 확인한 뒤 합친다. 급하면 먼저 합치고 MR에 사유를 남긴다.
5. **내가 설명하지 못하는 코드는 합치지 않는다.**
6. MR은 작게. WBS 카드 하나 = MR 하나.

## 보안

- `.env`와 API 키는 커밋하지 않는다. 키 이름은 `.env.example`에 값 없이 적는다.
- 수집한 원본 데이터, 모델 파일, `mlruns/`는 커밋하지 않는다.

## AI 에이전트

이 프로젝트는 AI 코딩 에이전트와 함께 개발한다. 에이전트가 읽는 규칙 파일은 아래 두 개다.

| 파일 | 읽는 에이전트 | 내용 |
|---|---|---|
| [CLAUDE.md](CLAUDE.md) | Claude Code (김기현·양정호) | 개발 규칙, 노션 WBS 카드 작업 방법, 학습노트·트러블슈팅 기록 양식 |
| [AGENTS.md](AGENTS.md) | Codex (김기현, 리뷰 전용) | 리뷰 체크리스트와 출력 형식. 파일은 수정하지 않는다 |

- 작업 시작: Claude Code에 `K04 진행해줘`처럼 WBS 카드 코드로 요청한다.
- 1차 리뷰: 김기현은 Codex, 양정호는 새 Claude Code 세션의 `/code-review`. 사람 리뷰(MR 규칙 4)는 그대로 한다.
- 공통 규칙을 바꾸면 `CLAUDE.md`와 `AGENTS.md`를 같은 MR에서 함께 고친다.
