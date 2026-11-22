# 팜잇 (FarmIt)

농사를 막 시작한 농업인 곁에서 재배부터 판매까지 판단을 돕는 AI 농사 도우미.
SSAFY 관통 프로젝트 · 양정호, 김기현 · 2026-10-19 ~ 2026-12-24

## 2026 대한민국 청년 CAREER FAIR AI 해커톤 제출본

| 항목 | 내용 |
|---|---|
| 팀 / 프로젝트 | 농잘알 / 팜잇 (FarmIt) |
| 서비스 | https://farmit.site |
| 시연 계정 | `farmitdemo` / `Demo2026farm` (가짜 데이터로 만든 심사용 계정, 회원별 하루 채팅 20회) |
| 제출 기준 버전 | 태그 `hackathon-submission` |
| 공개본 안내 | SSAFY GitLab 저장소의 develop 이력을 그대로 옮겼고, AI Hub 데이터로 학습한 사진 분류 가중치(`ml/vision/model/vision.onnx`)만 이력에서 뺐다. 서비스는 이 가중치를 쓰지 않는다 |


## 문서

| 문서 | 내용 |
|---|---|
| [docs/requirements.md](docs/requirements.md) | 요구사항 정의서 |
| [docs/screens.md](docs/screens.md) | 화면 목록 |
| [docs/erd.md](docs/erd.md) | ERD |
| [docs/api.md](docs/api.md) | API 명세서 |
| [docs/ml.md](docs/ml.md) | 가격 예측: 현재 모델(사과 v3), 사용법, 전국·저장성 품목 확장 검토 |
| [docs/infra-memory.md](docs/infra-memory.md) | 컨테이너 메모리 측정, 서버 사양 판단 |
| [docs/test-report.md](docs/test-report.md) | 통합 테스트 보고서: 필수 요구사항 체크리스트, 찾은 문제, 서버에 반영할 것 |

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
| frontend (Vue 3 + Vite) | http://localhost:5173 | `frontend/`가 마운트되어 저장 시 자동 새로고침. `/api`는 backend로 프록시. 패키지가 바뀌면 `rm -sf frontend` → `docker volume rm farmit_frontend-node-modules` → `up --build -d frontend` (이름 있는 볼륨이라 `-V`로는 새로 만들어지지 않는다) |
| backend (Django) | http://localhost:8000 | `backend/`가 마운트되어 코드 저장 시 자동 재시작 |
| mysql 8.4 | localhost:**3307** | DB 도구로 접속할 때. 컨테이너끼리는 `mysql:3306` |
| kafka 3.9 (KRaft) | localhost:**29092** | 내 PC에서만 열림. 컨테이너끼리는 `kafka:9092`. 볼륨이 없어 `down` 하면 토픽이 지워진다 |
| flink 1.20 | http://localhost:8081 | 웹 UI. 내 PC에서만 열림. `streaming/`이 `/opt/farmit/streaming`에 마운트된다 |

자주 쓰는 명령

```bash
docker compose -f infra/docker-compose.yml logs -f backend                    # 로그 보기
docker compose -f infra/docker-compose.yml exec backend python manage.py test # 테스트 (test_farmit DB 자동 생성·삭제)
docker compose -f infra/docker-compose.yml exec backend python manage.py makemigrations
docker compose -f infra/docker-compose.yml exec frontend npm test             # 프론트 단위 테스트 (vitest)
docker compose -f infra/docker-compose.yml down                               # 종료 (DB 데이터 유지)
docker compose -f infra/docker-compose.yml down -v                            # 종료 + DB 데이터 삭제

# Kafka 토픽 목록 / Flink SQL 콘솔
# Git Bash에서는 /opt/... 경로가 C:/Program Files/Git/opt/...로 바뀌어 실패한다. 앞에 MSYS_NO_PATHCONV=1 을 붙인다
docker compose -f infra/docker-compose.yml exec kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092 --list
docker compose -f infra/docker-compose.yml exec flink-jobmanager ./bin/sql-client.sh

# 코드 테이블 초기 데이터 (시장 32곳 = 수집 대상 5곳 + 나머지 27곳, 품목 312개). 여러 번 실행해도 중복되지 않는다
docker compose -f infra/docker-compose.yml exec backend python manage.py loaddata markets_collect markets_national items
```

- `items.json`의 품목은 실시간 경매 응답에 나온 것을 모은 것이다 (2026-11-19에 최근 7일치에서 빠진 87개를 더해 242개). 같은 날 정산 자료에만 나오는 농산·기타 품목 70개(최근 8주, 두릅·수수·머루 등)를 더해 312개다. 정산에만 나오는 수산물 207개는 농업인 대상 서비스라 넣지 않았다. 목록에 없는 품목이 실시간 경매에 나오면 수집기가 `item` 테이블에 바로 등록하고(로그 `새 품목 등록`, `item_id` 10000번부터) 그 낙찰도 저장한다. 이 품목은 DB에만 있고 `items.json`에는 없다. `items.json`에 품목을 더할 때는 pk를 9999 이하로 쓰고, DB에 이미 자동 등록된 품목 코드(`at_code`)는 넣지 않는다(넣으면 `loaddata`가 중복 오류로 멈춘다). 자동 등록 품목의 정산 가격은 다음 날 매일 수집부터 쌓이므로, 과거 추이가 필요하면 `settle.at_settle --all-items --start 날짜`로 다시 받는다.
- `markets_collect.json`은 처음 정한 5곳(4곳 + 가락), `markets_national.json`은 나머지 전국 시장이다. 2026-11-18부터 32곳 모두 수집 대상(`is_collect`)이다.
- 시장 위도·경도는 도매시장 위치(OpenStreetMap 기준, 2026-11-17)다. 원주·강릉·전주·익산·정읍·순천·안동 7곳은 2026-11-18 시장 장소·주소 자료로 보정했다(원주·순천·안동은 카카오맵 장소 좌표와 65m 이내, 정읍은 약 150m 차이). 지도 표시·거리 계산용 대표 좌표이며 출하 차량 진입점과는 다를 수 있다. 좌표가 `0`인 시장이 생기면 `/api/recommendations/now`는 거리를 비우고 운송비를 반영하지 않는다.
- 회원 위치 좌표(`user_profile.lat`·`lng`)는 시군구 중심 좌표다(OpenStreetMap Nominatim의 행정구역 대표 좌표, 2026-11-19, © OpenStreetMap contributors). 가입·내 정보 수정 때 `backend/codes/fixtures/sigungu_coords.json`에서 찾아 채운다. 시군구 목록(`frontend/src/constants/regions.js`)을 고치면 `python backend/codes/fixtures/build_sigungu_coords.py`로 다시 만든다.
- 판매 추천의 운송비는 `도로 거리 × km당 단가 + 통행료`(편도 한 번)다. 도로 거리·통행료는 카카오모빌리티 자동차 길찾기(`.env`의 `KAKAO_NAVI_KEY`, 1종 차량·하이패스 아님)로 시군구 중심 → 시장을 조회해 `market_route`에 저장하고 다시 쓴다. 한 시군구를 처음 조회할 때만 시장 수(32)만큼 부른다. 키가 없거나 조회에 실패하면 직선거리로 계산한다. 단가를 넣지 않은 회원은 기본 단가 170원/km(1톤 트럭 포터2 경유 연비 약 9.3km/L, 경유 약 1,600원/L로 잡은 연료비, `TRANSPORT_DEFAULT_COST_PER_KM`)를 쓴다.
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

#### 자동 실행 (Airflow, `batch/dags/collect.py`)

위 수집기를 Airflow가 스케줄대로 실행한다. 각자 인증키로 API를 부르므로 **기본으로는 뜨지 않는다** (`--profile airflow`). `.env`의 Airflow 키 4개(`POSTGRES_PASSWORD`, `AIRFLOW__DATABASE__SQL_ALCHEMY_CONN`, `AIRFLOW__API_AUTH__JWT_SECRET`, `AIRFLOW__CORE__FERNET_KEY`)를 먼저 채운다.

| DAG | 스케줄 (UTC) | 하는 일 |
|---|---|---|
| `collect_daily` | 매일 22:00 (한국 07:00) | 어제 정산·ASOS → 남은 한도로 과거 적재 이어 받기 |
| `collect_customs_monthly` | 매월 14일 22:00 | 관세청 수입량 (작년·올해) |
| `collect_ncpms_weekly` | 매주 화 22:00 | NCPMS 예찰 |
| `forecast_weekly` | 매주 일 23:00 (한국 월 08:00) | 데이터 점검 → Spark 피처 테이블(`ml/data/weekly_<품목코드>.csv`) → 품목마다 예측·`forecast` 저장, 과거 사례 다시 계산 (`batch/dags/forecast.py`, 점검이 실패하면 예측하지 않는다) |

```bash
docker compose -f infra/docker-compose.yml --profile airflow up --build -d
# 관리 화면: http://localhost:8080 (로그인 없음, 내 PC에서만 열린다). 새 DAG는 꺼져 있으니 화면에서 켠다
# 과거 적재가 어디까지 왔는지 (다음에 받을 날짜. 없으면 처음부터)
docker compose -f infra/docker-compose.yml exec airflow-scheduler airflow variables get backfill_next_at_settle
```

- 태스크가 실패하면 5분 간격으로 3번 다시 돈다. 시도마다 `collect_log`에 한 줄 남는다.
- DAG를 켜면 가장 최근에 놓친 스케줄 1회가 바로 돈다 (그보다 앞은 돌지 않는다. 빈 날짜는 과거 적재가 채운다).
- Spark 작업은 따로 Spark 서버 없이 scheduler 컨테이너 안에서 local 모드로 돈다. 손으로 실행:
  `docker compose -f infra/docker-compose.yml exec airflow-scheduler sh -c "cd /opt/farmit/spark && python -m features"`

#### 수집 상태 대시보드 (Kibana, K23)

Airflow DAG `collect_log_to_es`(`batch/dags/collect_log_es.py`)가 10분마다 MySQL `collect_log`의 새 행을 Elasticsearch `collect_log` 인덱스로 옮기고, Kibana 대시보드 **팜잇 수집 상태**가 이를 보여 준다. 이 DAG는 외부 API를 부르지 않아 처음부터 켜져 있다. 문서 id가 `collect_log.id`라서 다시 돌려도 중복되지 않는다.

| 패널 | 내용 |
|---|---|
| 소스별 성공·실패 | 출처마다 성공(초록)과 실패·부분 실패(빨강) 실행 수 |
| 출처별 마지막 수집 | 마지막 수집 시각·상태·저장 건수·API 호출 수 |
| 일별 API 호출 수 | 출처별 하루 호출 수와 aT 하루 한도 10,000 기준선 |
| 수집 실패·부분 실패 목록 | `success`가 아닌 실행과 실패 사유(`error_msg`) |

```bash
# Kibana도 관리 도구라 기본으로는 뜨지 않는다. Airflow(옮기는 DAG)와 같이 켠다
docker compose -f infra/docker-compose.yml --profile airflow --profile kibana up -d
# 대시보드 불러오기 (처음 한 번. 이미 있으면 덮어쓴다)
curl -X POST "localhost:5601/api/saved_objects/_import?overwrite=true" -H "kbn-xsrf: true" --form file=@infra/kibana/collect_status.ndjson
# 바로 옮기기 (10분을 기다리지 않을 때)
docker compose -f infra/docker-compose.yml exec airflow-scheduler airflow dags test collect_log_to_es
```

- 화면: http://localhost:5601/app/dashboards#/view/farmit-collect-status (내 PC에서만 열린다). 시각은 브라우저 시간대(한국)로 보인다.
- 대시보드를 화면에서 고쳤으면 다시 내보내 `infra/kibana/collect_status.ndjson`을 바꿔 커밋한다:
  `curl -X POST localhost:5601/api/saved_objects/_export -H "kbn-xsrf: true" -H "Content-Type: application/json" -d '{"objects":[{"type":"dashboard","id":"farmit-collect-status"}],"includeReferencesDeep":true,"excludeExportDetails":true}' -o infra/kibana/collect_status.ndjson`
- ES 인덱스를 지웠으면(`down -v` 등) 다음 실행이 `collect_log`를 처음부터 다시 옮긴다.

### 실시간 수집 (수집기 → Kafka → Flink → MySQL·알림)

```
기상청 API ─(weather-warning-producer, 10분마다)→ weather.warning.raw ─(Flink weather_warning)┬→ MySQL weather_warning (이력)
                                                                                         └→ weather.warning.event (새로·바뀐 특보만)
                                                                    ─(alert-consumer)→ MySQL special_event·alert (회원 알림)
```

`compose up` 하면 수집기(`weather-warning-producer`)와 알림 컨슈머(`alert-consumer`)는 자동으로 뜬다. **Flink 작업만 한 번 제출한다.**

주간농사정보 수집기(`weekly-farm-collector`)도 자동으로 뜬다. 하루 한 번 농사로에서 최근 호를 받아 "이번 주 농사 정보"를 채운다 (`.env`의 `NONGSARO_WEEKFARM_KEY` 필요. 없으면 `collect_log`에 실패로 남고 1시간마다 다시 시도한다).

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
- Flink 컨테이너만 다시 떠도(PC 재부팅, Docker 재시작) 작업은 사라진다. http://localhost:8081 에 작업이 없으면 `submit.sh`로 다시 제출한다.
- 체크포인트는 `flink-checkpoints` 볼륨(`/opt/flink/checkpoints`)에 파일로 저장한다. 기본값(JobManager 메모리)은 상태 하나가 5MB를 넘으면 체크포인트가 실패해 작업이 계속 재시작한다 (`realtime_price`의 중복 제거 상태가 전국 32곳에서 약 14MB). 작업을 Cancel하지 않고 컨테이너를 내리면 지난 작업의 체크포인트 폴더가 볼륨에 남는다. 쌓이면 `docker volume rm farmit_flink-checkpoints`로 지운다 (Flink를 내린 상태에서).
- Flink 작업을 새로 제출하면 "이미 본 특보" 상태가 비어 최근 6일치 이벤트가 한 번 다시 나간다. 알림은 DB UNIQUE 제약으로 중복되지 않는다.

#### 실시간 경매 (수집기 → Kafka `auction.trade.raw` → Flink → MySQL `auction_trade`, `realtime_price`)

경매 수집기는 각자 인증키로 3분마다 API를 부르므로 **기본으로는 뜨지 않는다** (`--profile auction`). 위 `loaddata markets_collect items`를 먼저 해 둔다.

```bash
# Flink 작업 제출 (compose up 뒤 한 번)
bash streaming/flink/submit.sh auction_trade    # 낙찰 1건 = 1행
bash streaming/flink/submit.sh realtime_price   # (정산일자, 시장, 품목)별 당일 집계

# 프로듀서: 한국 시간 00~12시 3분마다, 12~17시 30분마다 / 한 날짜 한 번 / 테스트
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
  ```bash
  # 작업이 없는 상태에서 실행한다. 토픽에 남아 있는 건 전체로 다시 집계한다 (지연 측정 탐침 2099-12-31 행도 다시 생기면 지운다)
  docker compose -f infra/docker-compose.yml exec kafka /opt/kafka/bin/kafka-consumer-groups.sh --bootstrap-server localhost:9092 --group flink-realtime-price --topic auction.trade.raw --reset-offsets --to-earliest --execute
  ```
- 제출된 작업 설정에는 DB 비밀번호가 들어 있어 Flink 웹 UI(내 PC에서만 열림)에서 보인다. 배포 설정에서는 다른 방법이 필요하다.

## 배포 (AWS Lightsail, Ubuntu 24.04)

개발용 `docker-compose.yml` 위에 덮어쓰기 파일을 겹쳐서 띄운다. 서버는 `master` 브랜치를 받는다.

| 파일 | 하는 일 |
|---|---|
| `infra/docker-compose.prod.yml` | gunicorn, Nginx가 화면 서빙, 외부 포트는 80뿐, 메모리 제한, 자동 재시작 |
| `infra/docker-compose.https.yml` | 443 + 인증서 + 자동 갱신(`certbot`). 인증서를 받은 뒤부터 붙인다 |
| `infra/scripts/server-setup.sh` | 서버 초기 설정 (Docker, 로그 크기 제한, 스왑 4GB, UTC, 예측 산출물 폴더 권한) |
| `infra/scripts/issue-cert.sh` | HTTPS 인증서 첫 발급 |
| `infra/scripts/deploy-check.sh` | 배포 점검 (health, 외부 포트, 응답 시간, Flink, Airflow) |
| `infra/cron/farmit` | 서버 주기 작업 (빠진 Flink 작업 다시 제출, airflow-scheduler 매일 재시작, 보도자료 매일 수집) |

### 처음 배포

콘솔에서 먼저 한다: Lightsail 인스턴스(8GB) 생성, 고정 IP 연결, 방화벽은 22(내 IP만)·80·443만 연다. 도메인 A 레코드를 고정 IP로 건다.

```bash
# 1. 코드 받기 + 서버 초기 설정 (끝나면 로그아웃했다가 다시 접속해야 docker 그룹이 적용된다)
git clone -b master https://lab.ssafy.com/s16/b05/pjt/999_final/final_kimkihyun_yangjeongho.git farmit && cd farmit
sudo bash infra/scripts/server-setup.sh

# 2. 환경 변수: 빈 값을 채운다. DJANGO_ALLOWED_HOSTS에는 도메인을 적는다 (이 값으로 인증서도 받는다)
cp .env.prod.example .env && chmod 600 .env && nano .env

# 3. 띄우기 (HTTP). 명령이 길어서 변수에 담아 쓴다
DC="docker compose -f infra/docker-compose.yml -f infra/docker-compose.prod.yml --profile airflow --profile auction"
$DC up -d --build

# 4. 인증서 받기 → Nginx가 HTTPS로 바뀐다. 이제부터는 https.yml을 같이 붙인다
bash infra/scripts/issue-cert.sh
DC="docker compose -f infra/docker-compose.yml -f infra/docker-compose.prod.yml -f infra/docker-compose.https.yml --profile airflow --profile auction"

# 5. 초기 데이터: 시장·품목 코드, 상담 근거 자료 수집(병해충·현장사례만 외부 API 약 1,900번·약 25분) → 색인
$DC exec backend python manage.py loaddata markets_collect markets_national items
$DC exec backend python manage.py rag_collect
$DC exec backend python manage.py rag_index
$DC exec backend python manage.py press_collect --days 30     # 보도자료 검색용 첫 적재. 그 뒤는 아래 cron이 매일 받는다

# 6. Flink 작업 제출 + 주기 작업 설치 (빠진 Flink 작업을 5분마다 다시 제출, airflow-scheduler를 매일 재시작, 보도자료 매일 수집)
for j in weather_warning auction_trade realtime_price; do bash streaming/flink/submit.sh $j; done
sudo cp infra/cron/farmit /etc/cron.d/farmit      # 레포가 /home/ubuntu/farmit 이 아니면 파일 안의 경로를 고친다

# 7. 점검. 실패 항목이 없어야 한다
bash infra/scripts/deploy-check.sh https://도메인
```

- Airflow DAG는 새 서버에서 모두 꺼져 있다. 관리 화면에서 켠다 (아래 SSH 터널).
- 주기 작업(`infra/cron/farmit`)이 한 일은 `journalctl -t farmit-flink -t farmit-airflow -t farmit-press`로 본다. `infra/cron/farmit`이 바뀌면 `sudo cp`를 다시 한다. Flink 작업이 다시 제출되면 `realtime_price`의 당일 집계가 그 시점부터 다시 세어진다 (위 "실시간 경매" 참고).
- 관리 포트의 외부 차단 확인은 서버 밖에서 봐야 정확하다. 내 PC(Git Bash)에서도 `bash infra/scripts/deploy-check.sh https://도메인`을 한 번 실행한다.
- 인증서는 `certbot` 컨테이너가 12시간마다 확인해 만료 30일 전에 갱신하고, Nginx가 하루 한 번 다시 읽는다.

### 수정한 코드 반영

개발은 지금처럼 각자 PC에서 하고 `develop`으로 MR 한다. 서버에 올릴 때 `develop` → `master` MR을 합친 뒤, 서버에서:

```bash
cd farmit && git pull
DC="docker compose -f infra/docker-compose.yml -f infra/docker-compose.prod.yml -f infra/docker-compose.https.yml --profile airflow --profile auction"
$DC up -d --build                                 # 코드가 이미지 안에 있어서 --build가 있어야 반영된다. migrate는 backend가 뜰 때 돈다
bash infra/scripts/deploy-check.sh https://도메인   # Flink 작업은 5분 안에 cron이 다시 제출한다. 바로 띄우려면 submit.sh
```

바꾼 곳에 따라 서버에서 할 일이 다르다.

| 바꾼 곳 | 서버에서 할 일 |
|---|---|
| `backend/`, `frontend/`, 실시간 수집기·알림 컨슈머 | `$DC up -d --build` (코드가 이미지 안에 있다) |
| `batch/dags/`, `batch/spark/`, `collectors/`의 배치 수집기, `ml/` | `git pull`만 하면 된다 (Airflow에 폴더가 마운트되어 있다). `requirements.txt`·`Dockerfile`을 바꿨으면 `--build` |
| `streaming/flink/*.sql` | 돌고 있는 작업은 옛 SQL 그대로다. Flink 화면(SSH 터널 8081)에서 그 작업을 Cancel 한 뒤 `bash streaming/flink/submit.sh <이름>` |
| 환경 변수 | 서버의 `.env`에 직접 넣고 `$DC up -d` (`.env`는 git에 없다) |
| 모델 변경(마이그레이션) | 반영 **전에** 아래 백업을 먼저 한다 |

```bash
# DB 백업 (마이그레이션이 있거나 큰 변경일 때 반영 전에)
$DC exec -T mysql sh -c 'mysqldump -uroot -p"$MYSQL_ROOT_PASSWORD" --single-transaction "$MYSQL_DATABASE"' | gzip > ~/farmit-$(date +%F).sql.gz

# 되돌리기: 반영 뒤 문제가 생기면 직전 커밋으로 돌아가 다시 빌드한다
git log --oneline -5              # 돌아갈 커밋 확인
git checkout <이전 커밋> && $DC up -d --build
git checkout master               # GitLab에서 문제 MR을 Revert 해 master를 고친 뒤 다시 pull 한다
```

- 되돌려도 이미 적용된 마이그레이션은 그대로 남는다. 컬럼을 지우거나 이름을 바꾸는 변경은 옛 코드와 맞지 않을 수 있으니, 백업을 해 두고 "컬럼 추가 → 코드 반영 → 나중에 옛 컬럼 삭제"처럼 나눠서 올린다.
- 반영은 한국 시간 17시 이후 저녁에 한다. 경매 수집(00~17시), 매일 수집(07:00), 주간 예측(월 08:00)과 겹치지 않는다.
- `realtime_price` 작업을 경매 시간 중에 다시 제출하면 당일 집계가 그 시점부터 다시 세어진다 (위 "실시간 경매" 참고).
- 한 번에 하나씩 작게 올린다. 여러 MR을 묶어 올리면 문제가 생겼을 때 원인을 찾기 어렵다.
- 반영하는 사람은 서버 SSH 접속이 필요하다. 각자 키를 만들어 공개 키를 서버 `~/.ssh/authorized_keys`에 추가하고(`.pem` 파일을 주고받지 않는다), Lightsail 방화벽 22번에 그 사람 IP를 넣는다.

### 관리 화면 보기 (SSH 터널)

Airflow·Flink·ES·Kibana는 서버의 `127.0.0.1`에만 열려 있다. 내 PC에서 터널을 건 뒤 `http://localhost:8080` 처럼 연다.

```bash
ssh -i <키 파일> -L 8080:localhost:8080 -L 8081:localhost:8081 ubuntu@<서버 IP>   # 8080 Airflow, 8081 Flink
```

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

## Credits / Licenses

이 저장소의 코드는 팀이 작성했다. 아래 외부 자원을 썼다. 상세 이용 조건은 프로젝트 소개서 별첨 「활용한 외부 자원·출처」 표와 같다.

### 데이터·API
| 자원 | 제공 | 이용 조건 | 쓰는 곳 |
|---|---|---|---|
| 도매시장 정산정보, 실시간 경매정보 | 한국농수산식품유통공사(aT), 공공데이터포털 | 이용허락범위 제한 없음 | 가격 통계·예측·실수령액 |
| ASOS 일자료, 기상특보 | 기상청, 공공데이터포털 | 공공누리 제1유형(출처표시) | 날씨, 산지 특보 알림 |
| 특일 정보 | 한국천문연구원, 공공데이터포털 | 이용허락범위 제한 없음 | 명절·휴일 |
| 품목별 국가별 수출입실적 | 관세청, 공공데이터포털 | 이용허락범위 제한 없음 | 수입량 급증 알림 |
| 병해충 정보·예찰 (NCPMS) | 농촌진흥청 | 출처 표시, 비상업 이용 (무료 비영리 서비스로 이용) | 상담 근거, 알림 |
| 현장기술지원 Q&A, 주간농사정보, 농업용어사전 | 농촌진흥청 농사로 | 공공누리 제1유형 | 상담 근거, 이번 주 농사 정보, 용어 풀이 |
| 농작업일정, 기술정보, 재해예방정보 | 농촌진흥청 농사로 | 이용허락범위 제한 없음 | 이번 달 할 일, 상담 근거 |
| 농업기술길잡이 | 농촌진흥청 | 공공누리 제4유형 — 본문은 쓰지 않고 목차·쪽 링크만 | 답변 아래 길잡이 링크 |
| 정책브리핑 보도자료 | 문화체육관광부 | 공공누리 제1유형 | 검색 |
| 한국어 위키백과 | 위키미디어 재단 | CC BY-SA 4.0 | 용어 풀이 보조 |
| 자동차 길찾기 (도로 거리·통행료) | 카카오모빌리티 | 카카오 API 이용약관 | 운송비 계산 |
| 작물 질병 진단 이미지 (153·147·146) | 한국지능정보사회진흥원(NIA) AI 허브 | AI 허브 이용정책 (연구·개발 목적, 데이터 재배포 금지) | 사진 분류 실험 모델 학습만 (서비스 미연결, 데이터·가중치 미포함). 이 결과물은 한국지능정보사회진흥원의 사업결과인 AI 허브 데이터를 활용했다 |

### AI 모델
| 자원 | 이용 조건 | 쓰는 곳 |
|---|---|---|
| Claude Haiku 5.5 (Anthropic API) | Anthropic 상용 이용약관 | 질문 의도 분류, 근거 기반 답변, 사진 판독 |
| multilingual-e5-small (intfloat) | MIT | 상담 근거 의미 검색 (서버에서 직접 실행) |

### 오픈소스
| 이름 | 라이선스 | 쓰는 곳 |
|---|---|---|
| Vue 3, Vue Router, Pinia, Vite, Vitest, axios | MIT | 프론트엔드 |
| Apache ECharts | Apache-2.0 | 차트 |
| Django, Django REST framework | BSD-3-Clause | 백엔드 |
| Apache Kafka, Apache Flink, Apache Airflow, Apache Spark | Apache-2.0 | 수집·스트리밍·배치 |
| Elasticsearch, Kibana | Elastic License 2.0 / AGPL-3.0 / SSPL 중 선택 (서버로만 실행, 수정·배포 안 함) | 검색, 대시보드 |
| MySQL | GPL-2.0 (서버로만 실행) | DB |
| scikit-learn | BSD-3-Clause | 가격 예측 |
| LightGBM, ONNX Runtime | MIT | 가격 예측, 사진 모델 실험 |
| XGBoost, MLflow | Apache-2.0 | 가격 예측, 모델 관리 |
| Anthropic Python SDK | MIT | LLM 호출 |

### 개발에 쓴 AI 도구
Claude Code (Anthropic, Claude Opus 5.5·Sonnet 5.5)로 코드·테스트·문서 초안을 만들고 팀이 검토·검증했다. 자세한 활용 내역은 해커톤 제출서의 「AI 활용내역」에 적었다.
