-- 실시간 경매 낙찰 건: Kafka auction.trade.raw → MySQL auction_trade (REQ-COL-002)
-- 프로듀서(collectors/auction)가 kg 환산·UTC 변환·item_id 매핑까지 끝낸 메시지를 그대로 저장한다.
-- 제출: bash streaming/flink/submit.sh auction_trade
--   ${MYSQL_...} 자리는 submit.sh가 .env 값으로 바꿔 넣는다 (비밀번호를 커밋하지 않기 위해)

SET 'pipeline.name' = 'auction_trade';
-- 체크포인트 때 Kafka 오프셋을 저장한다. 작업을 다시 띄우면 저장된 위치부터 이어서 읽는다
SET 'execution.checkpointing.interval' = '30s';

CREATE TABLE auction_src (
  source_key   STRING,
  auction_at   TIMESTAMP(0),   -- UTC
  market_id    STRING,
  item_id      INT,
  corp_name    STRING,
  grade        STRING,
  origin       STRING,
  price_per_kg DECIMAL(10, 1),
  volume_kg    DECIMAL(10, 1),
  collected_at TIMESTAMP(0)    -- UTC
  -- 메시지의 raw(원본)는 여기서 쓰지 않으므로 선언하지 않는다 (JSON의 나머지 필드는 무시된다)
) WITH (
  'connector' = 'kafka',
  'topic' = 'auction.trade.raw',
  'properties.bootstrap.servers' = 'kafka:9092',
  'properties.group.id' = 'flink-auction-trade',
  -- 처음에는 토픽 처음부터, 그 뒤에는 저장된 오프셋부터 읽는다
  'scan.startup.mode' = 'group-offsets',
  'properties.auto.offset.reset' = 'earliest',
  'format' = 'json',
  -- JSON이 아닌 메시지(콘솔 테스트 등)는 작업을 멈추지 않고 건너뛴다 (weather_warning.sql과 같게)
  'json.ignore-parse-errors' = 'true'
);

-- PRIMARY KEY를 선언하면 JDBC 싱크가 UPSERT(MySQL: INSERT ... ON DUPLICATE KEY UPDATE)로 쓴다.
-- 테이블의 UNIQUE(source_key)에 걸리므로 같은 건이 다시 와도 행이 늘지 않는다. id는 자동 증가라 넣지 않는다
CREATE TABLE auction_trade_sink (
  source_key   STRING,
  auction_at   TIMESTAMP(0),
  market_id    STRING,
  item_id      INT,
  corp_name    STRING,
  grade        STRING,
  origin       STRING,
  price_per_kg DECIMAL(10, 1),
  volume_kg    DECIMAL(10, 1),
  collected_at TIMESTAMP(0),
  PRIMARY KEY (source_key) NOT ENFORCED
) WITH (
  'connector' = 'jdbc',
  'url' = 'jdbc:mysql://mysql:3306/${MYSQL_DATABASE}',
  'table-name' = 'auction_trade',
  'username' = '${MYSQL_USER}',
  'password' = '${MYSQL_PASSWORD}',
  -- 1000건이 모이거나 2초가 지나면 한 번에 쓴다
  'sink.buffer-flush.max-rows' = '1000',
  'sink.buffer-flush.interval' = '2s'
);

-- 파싱에 실패해 건너뛴 메시지는 모든 값이 비어 있어 거른다
INSERT INTO auction_trade_sink
SELECT source_key, auction_at, market_id, item_id, corp_name, grade, origin, price_per_kg, volume_kg, collected_at
FROM auction_src
WHERE source_key IS NOT NULL;
