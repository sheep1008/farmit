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
| [docs/ml.md](docs/ml.md) | 가격 예측: 현재 모델(사과 v3), 사용법, 전국·저장성 품목 확장 검토 |

## 폴더 구조

```
backend/       Django API 서버 (config: 설정, api: health 등 공통)
frontend/      Vue 웹
collectors/    Open API 수집기. 실시간(Kafka로 보냄)은 수집기마다 폴더 하나 (auction, weather_warning). 배치 수집기는 common/(DB·UPSERT·재시도·collect_log)을 같이 쓴다
streaming/     Flink 작업 (flink/*.sql, submit.sh). 실시간 경로의 처리 단계
batch/         Spark 작업, Airflow DAG (배치 경로)
ml/            가격 예측 (farmit_ml 운영 패키지, config/ 모델 구성, experiments/ 전국 확장 실험). docs/ml.md 참고
rag/           재배·병해충 문서 수집, 색인, 검색
infra/         docker-compose, mysql/init(DB 초기화 스크립트), Nginx 등 실행 환경
docs/          요구사항, 화면, ERD, API 문서
.gitlab/       MR 템플릿
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
| kafka 3.9 (KRaft) | localhost:**29092** | 내 PC에서만 열림. 컨테이너끼리는 `kafka:9092`. 볼륨이 없어 `down` 하면 토픽이 지워진다 |
| flink 1.20 | http://localhost:8081 | 웹 UI. 내 PC에서만 열림. `streaming/`이 `/opt/farmit/streaming`에 마운트된다 |

자주 쓰는 명령

```bash
docker compose -f infra/docker-compose.yml logs -f backend                    # 로그 보기
docker compose -f infra/docker-compose.yml exec backend python manage.py test # 테스트 (test_farmit DB 자동 생성·삭제)
docker compose -f infra/docker-compose.yml exec backend python manage.py makemigrations
docker compose -f infra/docker-compose.yml down                               # 종료 (DB 데이터 유지)
docker compose -f infra/docker-compose.yml down -v                            # 종료 + DB 데이터 삭제

# Kafka 토픽 목록 / Flink SQL 콘솔
# Git Bash에서는 /opt/... 경로가 C:/Program Files/Git/opt/...로 바뀌어 실패한다. 앞에 MSYS_NO_PATHCONV=1 을 붙인다
docker compose -f infra/docker-compose.yml exec kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092 --list
docker compose -f infra/docker-compose.yml exec flink-jobmanager ./bin/sql-client.sh

# 코드 테이블 초기 데이터 (수집 대상 시장 5곳, 품목 155개). 여러 번 실행해도 중복되지 않는다
docker compose -f infra/docker-compose.yml exec backend python manage.py loaddata markets_collect items
```

- `markets_collect.json`의 시장 위도·경도는 `0`(임시)이다. 실제 좌표는 Y01(시장 33곳 초기 데이터)에서 채운다.
- `.env`의 `MYSQL_*` 값과 `infra/mysql/init/` 스크립트는 **DB 볼륨이 비어 있을 때(첫 실행)만** 적용된다. 바꾼 뒤에는 `down -v`로 볼륨을 지우고 다시 띄운다.
- backend는 시작할 때 `migrate`를 먼저 실행한다.

### 배치 수집기 (수집기 → MySQL, `collectors/common` 사용)

정산·날씨 등 하루 단위 수집기는 `collectors` 서비스에서 `python -m`으로 한 번씩 실행한다. 계속 떠 있지 않으므로 `--profile collect`로만 뜬다.

```bash
# 공통 모듈 테스트 (DB 테스트는 test_<DB이름> DB에서 돌고 끝나면 지운다. manage.py test와 동시에 돌리지 않는다)
docker compose -f infra/docker-compose.yml --profile collect run --rm collectors python -m unittest -v

# 수집기 실행 (모듈 이름은 수집기를 만들 때 정한다)
docker compose -f infra/docker-compose.yml --profile collect run --rm collectors python -m <모듈> ...

# 수집 기록 보기
docker compose -f infra/docker-compose.yml exec mysql sh -c 'mysql -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" "$MYSQL_DATABASE" -e "SELECT * FROM collect_log ORDER BY id DESC LIMIT 10"'
```

- 수집 함수에 `@collect_run("출처", daily_limit=...)`를 붙이면 성공·부분 실패·실패와 상관없이 `collect_log`에 한 줄 남는다. API는 `run.get()`으로 불러야 호출 수가 쌓이고 한도 전에 멈춘다.
- 저장은 `upsert()`(INSERT … ON DUPLICATE KEY UPDATE)로 한다. 같은 날짜를 다시 돌려도 테이블의 UNIQUE 키 때문에 행이 늘지 않는다.
- `requirements.txt`·`Dockerfile`을 바꾸면 `run` 앞에 `build collectors`를 한 번 한다.

### 실시간 수집 (수집기 → Kafka → Flink → MySQL·알림)

```
기상청 API ─(weather-warning-producer, 10분마다)→ weather.warning.raw ─(Flink weather_warning)┬→ MySQL weather_warning (이력)
                                                                                         └→ weather.warning.event (새로·바뀐 특보만)
                                                                    ─(alert-consumer)→ MySQL special_event·alert (회원 알림)
```

`compose up` 하면 수집기(`weather-warning-producer`)와 알림 컨슈머(`alert-consumer`)는 자동으로 뜬다. **Flink 작업만 한 번 제출한다.**

```bash
# Flink SQL 작업 제출 (compose up 뒤 한 번. 이미 돌고 있으면 건너뛴다)
bash streaming/flink/submit.sh weather_warning

# 로그 보기
docker compose -f infra/docker-compose.yml logs -f weather-warning-producer alert-consumer

# 수집기 테스트 (컨테이너 안에서)
docker compose -f infra/docker-compose.yml exec weather-warning-producer python -m unittest

# 호스트에서 수집기를 직접 돌릴 때 (처음 한 번 venv. Windows는 .venv/Scripts/python, WSL·Linux는 .venv/bin/python)
python -m venv collectors/weather_warning/.venv
collectors/weather_warning/.venv/Scripts/python -m pip install -r collectors/weather_warning/requirements.txt
collectors/weather_warning/.venv/Scripts/python collectors/weather_warning/producer.py --dry-run   # 보내지 않고 출력만
```

- Flink SQL 파일의 `${MYSQL_...}`는 `submit.sh`가 `.env` 값으로 채운다. SQL 파일에 비밀번호를 직접 적지 않는다.
- Kafka는 볼륨이 없어 `down` 하면 토픽과 Flink 작업이 사라진다. 다시 `up` 한 뒤 `submit.sh`부터 실행한다.
- Flink 작업을 새로 제출하면 "이미 본 특보" 상태가 비어 최근 6일치 이벤트가 한 번 다시 나간다. 알림은 DB UNIQUE 제약으로 중복되지 않는다.

#### 실시간 경매 (수집기 → Kafka `auction.trade.raw` → Flink → MySQL `auction_trade`, `realtime_price`)

경매 수집기는 각자 인증키로 2분마다 API를 부르므로 **기본으로는 뜨지 않는다** (`--profile auction`). 위 `loaddata markets_collect items`를 먼저 해 둔다.

```bash
# Flink 작업 제출 (compose up 뒤 한 번)
bash streaming/flink/submit.sh auction_trade    # 낙찰 1건 = 1행
bash streaming/flink/submit.sh realtime_price   # (정산일자, 시장, 품목)별 당일 집계

# 프로듀서: 한국 시간 00~12시 2분마다 / 한 날짜 한 번 / 테스트
docker compose -f infra/docker-compose.yml --profile auction up -d auction-producer
docker compose -f infra/docker-compose.yml --profile auction run --rm auction-producer python producer.py --once --date 2026-11-06
docker compose -f infra/docker-compose.yml --profile auction run --rm auction-producer python -m unittest
```

- Flink 작업을 다시 제출해도 Kafka 오프셋을 이어서 읽고, 같은 건은 `source_key`로 UPSERT되어 행이 늘지 않는다.
- 지연 측정(REQ-NFR-003: aT API 반영 후 5분 이내 화면 반영): 오늘 수집 기록으로 수집 주기·소요를 보고, 탐침 메시지로 Kafka→Flink→MySQL 지연을 잰 뒤 최악 지연을 더해 보여 준다. 탐침은 정산일자 2099-12-31로 보내고 끝나면 지운다.
  ```bash
  docker compose -f infra/docker-compose.yml exec -e KAFKA_BOOTSTRAP_SERVERS=kafka:9092 backend python manage.py measure_realtime_latency --probes 5
  ```
- `realtime_price`는 집계 전에 `source_key`로 중복을 걸러 같은 건이 두 번 더해지지 않는다. 다만 작업을 Cancel 후 새로 제출하면 집계 상태가 비어 그 뒤에 온 건부터 다시 센다 (당일 값이 작아질 수 있다). 당일 중에 다시 띄워야 하면 `realtime_price`의 오늘 행을 지우고 소비자 그룹 `flink-realtime-price` 오프셋을 처음으로 돌린 뒤 제출한다.
- 제출된 작업 설정에는 DB 비밀번호가 들어 있어 Flink 웹 UI(내 PC에서만 열림)에서 보인다. 배포 설정에서는 다른 방법이 필요하다.

## 개발 규칙

- **시간:** DB에는 UTC로 저장하고(Django `USE_TZ=True`, MySQL `default-time-zone=+00:00`), 화면·API 응답에서 Asia/Seoul로 바꿔 보여 준다. 수집기·배치도 UTC로 저장한다.
- **단위:** 가격은 원/kg, 물량은 kg으로 저장한다.
- **코드값:** 시장·품목 코드는 코드에 직접 쓰지 않고 market, item 테이블에서 읽는다.

## 브랜치

```
master    배포용. 발표·배포 시점에만 develop에서 합친다
develop   개발 통합. 모든 작업은 여기로 합친다
feature/ fix/ docs/ chore/   작업 브랜치 (develop에서 만들어 develop으로 MR)
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
