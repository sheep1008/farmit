-- 기상특보: Kafka weather.warning.raw → MySQL weather_warning (REQ-COL-004)
-- 제출: bash streaming/flink/submit.sh weather_warning
--   ${MYSQL_...} 자리는 submit.sh가 .env 값으로 바꿔 넣는다 (비밀번호를 커밋하지 않기 위해)
-- 스트리밍 작업이라 한 번 제출하면 계속 떠서 새 메시지를 저장한다 (Flink UI: localhost:8081)

SET 'pipeline.name' = 'weather_warning';
-- 체크포인트 때 읽은 위치(offset)를 Kafka에 기록한다. 작업을 다시 띄우면 그 다음부터 읽는다
SET 'execution.checkpointing.interval' = '30s';

CREATE TABLE weather_warning_raw (
  source_key   STRING,
  announced_at TIMESTAMP(3),
  region_code  STRING,
  region_name  STRING,
  warning_type STRING,
  level        STRING,
  status       STRING
) WITH (
  'connector' = 'kafka',
  'topic' = 'weather.warning.raw',
  'properties.bootstrap.servers' = 'kafka:9092',
  'properties.group.id' = 'flink-weather-warning',
  -- 기록된 위치부터 읽고, 처음이면(기록 없음) 토픽 맨 앞부터 읽는다
  'scan.startup.mode' = 'group-offsets',
  'properties.auto.offset.reset' = 'earliest',
  'format' = 'json',
  'json.timestamp-format.standard' = 'ISO-8601',  -- "2026-11-06T03:00:00" (UTC)
  -- JSON이 아닌 메시지(콘솔 테스트 등)는 작업을 멈추지 않고 건너뛴다
  'json.ignore-parse-errors' = 'true'
);

-- PRIMARY KEY를 선언하면 JDBC 싱크가 upsert(INSERT ... ON DUPLICATE KEY UPDATE)로 쓴다.
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

-- 파싱에 실패해 건너뛴 메시지는 모든 값이 비어 있어 거른다
-- (주의) sql-client는 줄 끝이 ;여야 문장 끝으로 본다. ; 뒤에 주석을 붙이면 실행되지 않는다
INSERT INTO weather_warning_sink
SELECT * FROM weather_warning_raw
WHERE source_key IS NOT NULL;
