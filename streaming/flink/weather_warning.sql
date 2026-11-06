-- 기상특보: Kafka weather.warning.raw → ① MySQL weather_warning (이력, REQ-COL-004)
--                                   → ② Kafka weather.warning.event (새로 생기거나 바뀐 특보만, 알림용 REQ-ALT-001)
-- 제출: bash streaming/flink/submit.sh weather_warning
--   ${MYSQL_...} 자리는 submit.sh가 .env 값으로 바꿔 넣는다 (비밀번호를 커밋하지 않기 위해)
-- 스트리밍 작업이라 한 번 제출하면 계속 떠서 새 메시지를 처리한다 (Flink UI: localhost:8081)
--
-- 수집기는 10분마다 최근 6일치를 통째로 다시 보낸다(API가 "새 것만"을 주지 않으므로).
-- ①은 upsert라 그래도 행이 늘지 않고, ②는 처음 보는 (source_key, status)만 내보내 알림이 반복되지 않게 한다.

SET 'pipeline.name' = 'weather_warning';
-- 체크포인트 때 읽은 위치(offset)를 Kafka에 기록한다. 작업을 다시 띄우면 그 다음부터 읽는다
SET 'execution.checkpointing.interval' = '30s';
-- ②가 기억하는 "이미 본 특보" 상태를 14일 뒤 지운다. 수집 범위(6일)보다 길어야 같은 특보를 다시 내보내지 않는다
SET 'table.exec.state.ttl' = '14 d';

CREATE TABLE weather_warning_raw (
  source_key   STRING,
  announced_at TIMESTAMP(3),
  region_code  STRING,
  region_name  STRING,
  warning_type STRING,
  level        STRING,
  status       STRING,
  effective_at TIMESTAMP(3),   -- 발효 시각 (발표 때만). ②에만 싣는다
  ended_at     TIMESTAMP(3),   -- 해제 시각 (해제 때만). ②에만 싣는다
  proc AS PROCTIME()           -- 들어온 순서. ②에서 "처음 본 것"을 고르는 기준
) WITH (
  'connector' = 'kafka',
  'topic' = 'weather.warning.raw',
  'properties.bootstrap.servers' = 'kafka:9092',
  'properties.group.id' = 'flink-weather-warning',
  -- 기록된 위치부터 읽고, 처음이면(기록 없음) 토픽 맨 앞부터 읽는다
  'scan.startup.mode' = 'group-offsets',
  'properties.auto.offset.reset' = 'earliest',
  'format' = 'json',
  'json.timestamp-format.standard' = 'ISO-8601',
  -- JSON이 아닌 메시지(콘솔 테스트 등)는 작업을 멈추지 않고 건너뛴다
  'json.ignore-parse-errors' = 'true'
);

-- ① PRIMARY KEY를 선언하면 JDBC 싱크가 upsert(INSERT ... ON DUPLICATE KEY UPDATE)로 쓴다.
-- MySQL의 source_key UNIQUE 제약에 걸리면 새 행 대신 기존 행을 덮어써서 중복이 생기지 않는다.
-- id(자동 증가)는 MySQL이 채우므로 여기 적지 않는다
CREATE TABLE weather_warning_sink (
  source_key   STRING,
  announced_at TIMESTAMP(3),
  region_code  STRING,
  region_name  STRING,
  warning_type STRING,
  level        STRING,
  status       STRING,
  PRIMARY KEY (source_key) NOT ENFORCED
) WITH (
  'connector' = 'jdbc',
  'url' = 'jdbc:mysql://mysql:3306/${MYSQL_DATABASE}',
  'table-name' = 'weather_warning',
  'username' = '${MYSQL_USER}',
  'password' = '${MYSQL_PASSWORD}',
  'sink.buffer-flush.interval' = '1s',
  'sink.buffer-flush.max-rows' = '500'
);

-- ② 새로 생기거나 바뀐 특보. 메시지 key는 source_key
CREATE TABLE weather_warning_event (
  source_key   STRING,
  announced_at TIMESTAMP(3),
  region_code  STRING,
  region_name  STRING,
  warning_type STRING,
  level        STRING,
  status       STRING,
  effective_at TIMESTAMP(3),
  ended_at     TIMESTAMP(3)
) WITH (
  'connector' = 'kafka',
  'topic' = 'weather.warning.event',
  'properties.bootstrap.servers' = 'kafka:9092',
  'key.format' = 'raw',
  'key.fields' = 'source_key',
  'value.format' = 'json',
  'value.json.timestamp-format.standard' = 'ISO-8601',
  'sink.delivery-guarantee' = 'at-least-once'
);

-- 두 INSERT를 작업 하나로 묶는다 (토픽을 한 번만 읽는다)
-- (주의) sql-client는 줄 끝이 ;여야 문장 끝으로 본다. ; 뒤에 주석을 붙이면 실행되지 않는다
EXECUTE STATEMENT SET
BEGIN

-- 파싱에 실패해 건너뛴 메시지는 모든 값이 비어 있어 거른다
INSERT INTO weather_warning_sink
SELECT source_key, announced_at, region_code, region_name, warning_type, level, status
FROM weather_warning_raw
WHERE source_key IS NOT NULL;

-- (source_key, status)별로 처음 들어온 1건만 내보낸다 (Flink 중복 제거: ROW_NUMBER ... = 1).
-- 같은 특보가 "발표 → 해제"로 바뀌면 status가 달라 새 이벤트로 나간다.
-- (주의) 작업을 새로 제출하면 이 상태가 비어 최근 6일치가 한 번 다시 나간다. 알림 쪽도 중복을 막는다
INSERT INTO weather_warning_event
SELECT source_key, announced_at, region_code, region_name, warning_type, level, status, effective_at, ended_at
FROM (
  SELECT *, ROW_NUMBER() OVER (PARTITION BY source_key, status ORDER BY proc ASC) AS rn
  FROM weather_warning_raw
  WHERE source_key IS NOT NULL
)
WHERE rn = 1;

END;
