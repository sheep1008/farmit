# 컨테이너 메모리 측정 (K11)

AWS EC2 서버 사양을 정하기 위한 자료다. 서비스가 늘면(Spark, Elasticsearch·Kibana, ML) 다시 재서 아래에 덧붙인다.

## 1. 측정 조건 (2026-11-15)

- 장비: Windows 11 + Docker Desktop (WSL2), Docker에 CPU 8개 · 메모리 7.6 GiB 할당
- 띄운 것: `docker compose -f infra/docker-compose.yml --profile airflow --profile auction up -d` (컨테이너 13개 전부)
  - Flink 작업 3개 제출됨 (`weather_warning`, `auction_trade`, `realtime_price`)
  - MySQL에 `settle_price` 약 405만 행 (2018-01 ~ 2026-11 정산 과거 적재 뒤)
  - 경매 프로듀서는 한국 시간 00~12시에만 API를 부른다. 측정은 14시대라 대기 상태다
- 방법: 띄우고 1분 뒤 `docker stats --no-stream`을 20초 간격으로 5번 → 평균·최대.
  "태스크 실행 중"은 `collect_ncpms_weekly`를 실행하면서 10번 잰 최대값
- 일회성 컨테이너(`airflow-init`, `kafka-init`)는 끝나고 종료되므로 뺀다

## 2. 결과

| 묶음 | 컨테이너 | 평균 (MiB) | 최대 (MiB) | 태스크 실행 중 최대 (MiB) |
|---|---|---:|---:|---:|
| 배치 | airflow-scheduler | 713 | 713 | 844 |
| 배치 | airflow-apiserver | 269 | 269 | 269 |
| 배치 | airflow-dag-processor | 165 | 166 | 165 |
| 배치 | airflow-db (Postgres) | 59 | 61 | 60 |
| DB | mysql | 563 | 564 | |
| 실시간 | flink-taskmanager | 521 | 536 | |
| 실시간 | flink-jobmanager | 470 | 484 | |
| 실시간 | kafka | 459 | 502 | |
| 실시간 | alert-consumer | 39 | 39 | |
| 실시간 | weather-warning-producer | 26 | 29 | |
| 실시간 | auction-producer | 22 | 22 | |
| 웹 | backend (Django runserver) | 85 | 85 | |
| 웹 | frontend (Vite dev server) | 80 | 81 | |
| | **합계** | **3,472** | **3,552** | |

묶음별 합계(평균): 배치 1,206 · 실시간 1,537 · DB 563 · 웹 165 MiB.

## 3. 읽는 법

- **airflow-scheduler가 가장 크다.** LocalExecutor라 태스크가 scheduler 안에서 돈다. 막 띄웠을 때는 330 MiB였는데,
  정산 과거 적재(약 100개월, 1시간 반)를 돈 뒤 713 MiB로 늘었고 줄지 않았다. 파이썬 프로세스가 한 번 잡은 메모리를 바로 돌려주지 않기 때문으로 본다.
  큰 작업 중에는 1 GiB 가까이 잡아 둔다.
- **Kafka·Flink는 JVM이라 기본 400~500 MiB씩 잡는다.** 데이터 양과 거의 상관없다. 세 개 합쳐 약 1.5 GiB로 가장 큰 묶음이다.
- **배포 때는 웹 묶음이 바뀐다.** frontend는 빌드한 정적 파일을 Nginx가 내보내므로 Vite dev server(80 MiB)가 빠지고,
  backend는 runserver 대신 gunicorn 워커 수만큼 늘어난다 (아직 재지 않았다).

## 4. 서버 사양 판단 (가정 포함)

| 항목 | MiB | 근거 |
|---|---:|---|
| 지금 컨테이너 전부 | 약 3,600 | 위 최대 합계 |
| Airflow 큰 작업 여유 | +400 | scheduler 실행 중 최대 − 평균 (과거 적재는 한 번이면 끝난다) |
| OS·Docker 자체 | +500 | 가정 |
| **지금 기준 필요** | **약 4,500** | |
| Spark 실행 중 (K12) | +1,100 | 주 1회 몇십 초. 5절 |
| 앞으로 추가 (아직 없음) | Elasticsearch·Kibana, ML 예측 | 재지 않음. 특히 Elasticsearch는 JVM 힙을 따로 잡는다 |

- 지금 구성만이면 **메모리 8 GiB 서버**에 들어간다 (여유 약 3.5 GiB).
- Spark·Elasticsearch까지 한 대에 올리면 8 GiB로는 빠듯할 가능성이 크다. 그 서비스가 들어오면 이 문서에 다시 재서 16 GiB로 올릴지,
  JVM 힙을 줄일지(Kafka·Flink·ES), Airflow를 줄일지(scheduler 재시작 주기, 병렬 수) 정한다.

## 5. Spark 추가 (K12, 2026-11-15)

- Spark는 따로 컨테이너를 띄우지 않는다. Airflow 태스크가 scheduler 컨테이너 안에서 pyspark를 local 모드로 실행한다
  (`spark.driver.memory` 1g, `batch/spark/common.py`). 그래서 상시 메모리는 늘지 않고, 태스크가 도는 동안만 늘어난다.
- 측정: `airflow dags test build_features_weekly`(피처 테이블, 사과 4개 시장 × 463주)를 실행하면서 2초 간격으로 `docker stats`를 40번 쟀다.
  같은 날 컴퓨터를 다시 켠 뒤라 scheduler 기준값이 2절(713 MiB)보다 작다.

| 시점 | airflow-scheduler (MiB) |
|---|---:|
| 실행 전 | 440 |
| Spark 실행 중 최대 | 1,574 |
| 끝난 뒤 | 404 |

- 늘어나는 양은 약 1.1 GiB(JVM 드라이버 힙 1g + 파이썬)이고, 매주 한 번 약 40초다. 끝나면 JVM 프로세스가 종료돼 메모리를 돌려준다.
- 4절 기준(약 4.5 GiB)에 더하면 실행 중 약 5.6 GiB라 8 GiB 서버에 아직 들어간다. 피처(일 23:00 UTC)는 하루 수집(22:00 UTC) 한 시간 뒤라
  보통 겹치지 않는다. 과거 적재가 남아 있으면 그 태스크가 몇 시간 돌아 겹칠 수 있다 (지금은 과거 적재가 끝나 바로 끝난다).

## 6. 다시 측정 — Elasticsearch·Kibana·RAG 추가 뒤 (T02, 2026-11-20)

- 조건: 같은 PC인데 Docker 메모리 할당이 7.6 → 15.5 GiB로 늘었다. 컨테이너 16개 전부(`airflow`·`auction`·`kibana` profile 포함), 띄운 지 5시간 뒤.
  `docker stats --no-stream`을 15초 간격으로 3번 쟀고 값이 거의 같아 평균만 적는다. 메모리 제한은 아무 컨테이너에도 걸려 있지 않다.

| 묶음 | 컨테이너 | 지금 (MiB) | 11-15 (MiB) | 배포 때 |
|---|---|---:|---:|---|
| 검색 | elasticsearch | 1,699 | 없었음 | 힙은 512MB 그대로. 나머지는 파일 캐시라 제한을 걸면 줄어든다 |
| 검색 | kibana | 654 | 없었음 | 평소에는 끈다 (profile) |
| 실시간 | kafka | 1,140 | 459 | 힙을 묶는다 (기본 1GB) |
| 실시간 | flink-jobmanager | 1,061 | 470 | 프로세스 크기를 묶는다 (기본 1,600MB) |
| 실시간 | flink-taskmanager | 820 | 521 | 그대로 (작업 3개) |
| 실시간 | alert-consumer | 116 | 39 | 그대로 |
| 실시간 | auction·weather 프로듀서 | 103 | 48 | 그대로 |
| 배치 | airflow-scheduler | 1,120 | 713 | 태스크가 돌수록 늘어난다. 주기적으로 재시작 |
| 배치 | airflow-apiserver | 294 | 269 | 그대로 (태스크 실행 API를 겸해 끌 수 없다) |
| 배치 | airflow-dag-processor | 187 | 165 | 그대로 |
| 배치 | airflow-db | 59 | 59 | 그대로 |
| 배치 | weekly-farm-collector | 23 | 없었음 | 그대로 |
| DB | mysql | 710 | 563 | 그대로 |
| 웹 | backend (runserver + 임베딩 모델) | 942 | 85 | gunicorn으로 바뀐다. 다시 잰다 |
| 웹 | frontend (Vite dev server) | 262 | 80 | Nginx 정적 서빙으로 바뀐다 (약 10MiB) |
| | **합계** | **약 9,190** | 3,472 | |

### 읽는 법

- **5일 만에 3.5 → 9.2 GiB가 됐다.** 늘어난 이유는 세 가지다.
  ① 새 서비스: Elasticsearch·Kibana 약 2.35 GiB.
  ② backend가 RAG 임베딩 모델(multilingual-e5-small)을 메모리에 올린다: +0.85 GiB.
  ③ Docker 할당이 2배가 되면서 JVM(Kafka·Flink)과 파일 캐시가 더 넓게 잡는다: Kafka·Flink만 +1.6 GiB. 일이 늘어서가 아니라 제한이 없어서 커진 것이다.
- **그대로 올리면 8 GiB 서버에 들어가지 않는다.** ③은 제한을 걸면 11-15 수준으로 돌아갈 것으로 본다 (가정, 2단계에서 확인).

### 8 GiB에 넣기 위한 목표 (2단계 배포용 compose에서 제한을 걸고 다시 잰다)

| 줄이는 것 | 예상 절감 (MiB) |
|---|---:|
| Kibana 끄기 | 650 |
| Kafka 힙 384MB | 550 |
| Flink jobmanager 프로세스 크기 768MB | 300 |
| Elasticsearch 컨테이너 제한 1.2GB | 500 |
| frontend → Nginx | 250 |
| backend gunicorn 워커 1개 + 스레드 | 300 |
| **줄인 뒤 합계** | **약 6,600** |

- OS·Docker 약 500 MiB를 더하면 약 7.1 GiB다. 8 GiB 서버(실제 쓸 수 있는 양 약 7.6 GiB)에 **여유 약 0.5 GiB로 빠듯하게** 들어간다.
  Spark가 도는 40초(+1.1 GiB, 주 1회)는 스왑 4GB로 넘긴다.
- **판단 기준:** 2단계에서 제한을 건 채로 잰 합계가 6.8 GiB 이하이면 8 GiB 서버, 넘으면 16 GiB 서버로 간다.

### 서버·비용 (AWS Lightsail, 서울 리전. 요금은 가입 화면에서 다시 확인한다)

| 요금제 | 메모리 | 디스크 | 월 요금 |
|---|---:|---:|---:|
| 8GB | 8 GiB / 2 vCPU | 160GB | 약 44달러 |
| 16GB | 16 GiB / 4 vCPU | 320GB | 약 84달러 |

- EC2 대신 Lightsail을 고른 이유: 한 달 이상 계속 켜 둘 계획인데 같은 8 GiB인 EC2 t3.large는 디스크·공인 IP를 합쳐 월 약 83달러다. Lightsail은 디스크·고정 IP·트래픽이 요금에 들어 있다.
- 디스크: 지금 PC의 Docker 볼륨이 5.8GB(MySQL·ES·모델)이고 이미지가 수십 GB다. 160GB면 충분하다. 로그 크기 제한은 2단계에서 건다.
- 월 비용 계산: 요금제 월 요금 + S3 백업(GB당 약 0.025달러) + LLM 호출료. 고정 IP는 인스턴스에 붙어 있는 동안 무료다.

### 제한을 걸고 잰 결과 (T02 2단계, 2026-11-20)

- 조건: `docker-compose.yml` + `docker-compose.prod.yml`로 띄움 (`airflow`·`auction` profile, Kibana 끔). Flink 작업 3개 제출, 띄운 지 약 10분 뒤 20초 간격 3번.

| 컨테이너 | 개발용 (MiB) | 배포용 (MiB) | 바꾼 것 |
|---|---:|---:|---|
| elasticsearch | 1,699 | 1,110 | `mem_limit: 1200m` |
| kibana | 654 | 0 | 끔 |
| kafka | 1,140 | 442 | 힙 384MB |
| flink-jobmanager | 1,061 | 557 | 프로세스 크기 1,024MB |
| flink-taskmanager | 820 | 570 | 그대로 (막 띄운 값) |
| airflow 4개 | 1,660 | 825 | 그대로 (막 띄운 값) |
| mysql | 710 | 516 | 그대로 (막 띄운 값) |
| backend | 942 | 142 | gunicorn 워커 1개. 임베딩 모델을 아직 안 올린 값 |
| frontend | 262 | 29 | Nginx |
| 나머지 4개 | 242 | 201 | 그대로 |
| **합계** | **9,190** | **4,390** | |

- **임베딩 모델:** 채팅·증상 진단을 처음 부를 때 backend에 올라간다. 따로 재니 약 880 MiB였다 (`manage.py shell`에서 `embed.embed_query` 앞뒤 최대 메모리). 더하면 **약 5.3 GiB**다.
- **막 띄운 값이라 낮게 나온 것:** airflow-scheduler(393 → 오래 돌면 1,120), mysql(516 → 710), flink-taskmanager(570 → 820) 등. 개발용에서 5시간 돈 값으로 바꿔 넣으면 **최악 약 6.9 GiB**다.
- **판단:** OS·Docker 0.5 GiB를 더하면 5.8 ~ 7.4 GiB. 8 GiB 서버(쓸 수 있는 양 약 7.6 GiB)에 들어가지만 최악일 때 여유가 0.2 GiB뿐이다.
  하루 수집(22:00 UTC)이 한 번 돈 뒤 다시 재서 6.8 GiB 이하이면 8GB 요금제, 넘으면 16GB 요금제로 정한다. 8GB로 가면 스왑 4GB와 airflow-scheduler 주기 재시작을 넣는다 (T03).
