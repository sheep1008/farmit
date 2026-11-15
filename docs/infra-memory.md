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
| 앞으로 추가 (아직 없음) | Spark(K12), Elasticsearch·Kibana, ML 예측 | 재지 않음. 특히 Elasticsearch는 JVM 힙을 따로 잡는다 |

- 지금 구성만이면 **메모리 8 GiB 서버**에 들어간다 (여유 약 3.5 GiB).
- Spark·Elasticsearch까지 한 대에 올리면 8 GiB로는 빠듯할 가능성이 크다. 그 서비스가 들어오면 이 문서에 다시 재서 16 GiB로 올릴지,
  JVM 힙을 줄일지(Kafka·Flink·ES), Airflow를 줄일지(scheduler 재시작 주기, 병렬 수) 정한다.
