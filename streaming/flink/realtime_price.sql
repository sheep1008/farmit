-- 당일 경매 집계: Kafka auction.trade.raw → MySQL realtime_price (REQ-PRC-004, REQ-NFR-003)
-- 낙찰 건이 들어올 때마다 (정산일자, 시장, 품목) 한 행의 평균·최저·최고·물량·건수·마지막 낙찰 시각을 갱신한다.
-- auction_trade.sql과 같은 토픽을 다른 소비자 그룹으로 읽는다 (두 작업이 서로의 오프셋에 영향을 주지 않는다).
-- 제출: bash streaming/flink/submit.sh realtime_price
--   ${MYSQL_...} 자리는 submit.sh가 .env 값으로 바꿔 넣는다 (비밀번호를 커밋하지 않기 위해)

SET 'pipeline.name' = 'realtime_price';
-- 체크포인트 때 Kafka 오프셋과 집계 상태(합계·건수 등)를 같이 저장한다
SET 'execution.checkpointing.interval' = '30s';
-- 키별 상태를 2일 동안 갱신이 없으면 지운다. 날짜가 키에 들어가므로 지난 날짜의 상태가 끝없이 쌓이지 않게 한다
--   (2일: 자정 근처에 늦게 도착한 건도 받을 수 있게 하루 여유를 둔다)
SET 'table.exec.state.ttl' = '2 d';
-- LOCALTIMESTAMP(updated_at)를 UTC로 만든다. DB는 UTC로 저장한다
SET 'table.local-time-zone' = 'UTC';

CREATE TABLE auction_src (
  source_key   STRING,
  auction_at   TIMESTAMP(0),   -- UTC
  market_id    STRING,
  item_id      INT,
  price_per_kg DECIMAL(10, 1),
  volume_kg    DECIMAL(10, 1),
  -- 원본 중 정산일자만 꺼낸다 ("2026-11-06" 모양). 집계 날짜의 기준. RAW는 Flink SQL 예약어라 백틱으로 감싼다
  `raw`        ROW<trd_clcln_ymd STRING>,
  -- 처리 시각. 아래 중복 제거에서 "먼저 들어온 건"을 고르는 기준으로만 쓴다
  proc_time AS PROCTIME()
  -- 집계에 쓰지 않는 필드(corp_name, grade 등)는 선언하지 않는다 (JSON의 나머지 필드는 무시된다)
) WITH (
  'connector' = 'kafka',
  'topic' = 'auction.trade.raw',
  'properties.bootstrap.servers' = 'kafka:9092',
  'properties.group.id' = 'flink-realtime-price',
  -- 처음에는 토픽 처음부터, 그 뒤에는 저장된 오프셋부터 읽는다
  'scan.startup.mode' = 'group-offsets',
  'properties.auto.offset.reset' = 'earliest',
  'format' = 'json',
  'json.ignore-parse-errors' = 'true'
);

-- PRIMARY KEY = 테이블의 UNIQUE(trade_date, market_id, item_id). 이 키로 UPSERT 한다. id는 자동 증가라 넣지 않는다
CREATE TABLE realtime_price_sink (
  trade_date      DATE,
  market_id       STRING,
  item_id         INT,
  avg_price       DECIMAL(10, 1),
  min_price       DECIMAL(10, 1),
  max_price       DECIMAL(10, 1),
  volume_kg       DECIMAL(12, 1),
  trade_count     INT,
  last_auction_at TIMESTAMP(0),
  updated_at      TIMESTAMP(0),
  PRIMARY KEY (trade_date, market_id, item_id) NOT ENFORCED
) WITH (
  'connector' = 'jdbc',
  'url' = 'jdbc:mysql://mysql:3306/${MYSQL_DATABASE}',
  'table-name' = 'realtime_price',
  'username' = '${MYSQL_USER}',
  'password' = '${MYSQL_PASSWORD}',
  -- 같은 키의 갱신은 버퍼 안에서 마지막 값 하나로 합쳐져 쓰인다. 2초마다 쓰므로 지연은 몇 초 수준
  'sink.buffer-flush.max-rows' = '1000',
  'sink.buffer-flush.interval' = '2s'
);

-- 1) 중복 제거: 프로듀서는 2분마다 겹치는 구간을 다시 보내므로 같은 낙찰 건(source_key)이 여러 번 온다.
--    auction_trade는 UPSERT라 괜찮지만, 집계는 그대로 두면 물량·건수가 두 번 더해진다.
--    source_key별로 처음 들어온 1건만 남긴다 (Flink가 "첫 건 유지" 중복 제거로 인식해 추가만 있는 스트림이 된다)
CREATE TEMPORARY VIEW auction_dedup AS
SELECT source_key, auction_at, market_id, item_id, price_per_kg, volume_kg, `raw`.trd_clcln_ymd AS settle_ymd
FROM (
  SELECT *,
         ROW_NUMBER() OVER (PARTITION BY source_key ORDER BY proc_time ASC) AS rn
  FROM auction_src
  WHERE source_key IS NOT NULL   -- 파싱에 실패해 건너뛴 메시지는 모든 값이 비어 있다
)
WHERE rn = 1;

-- 2) 집계: 정산일자(trd_clcln_ymd) 기준으로 묶는다.
--    정산일자 D에는 전날(D-1) 오후 경매분도 들어 있어, 낙찰 시각의 날짜로 묶으면 하루치가 둘로 갈린다.
--    다음 날 settle_price(trade_date = 정산일자)와 같은 날짜로 맞아야 "확정" 가격과 비교할 수 있다.
--    원본에 정산일자가 없으면(이론상) 낙찰 시각의 한국 날짜(UTC + 9시간)로 대신한다.
--    GROUP BY 결과는 새 건이 올 때마다 그 키의 행이 바뀌는 "갱신 스트림"이고, 싱크가 키로 UPSERT 한다
INSERT INTO realtime_price_sink
SELECT
  trade_date,
  market_id,
  item_id,
  -- 물량 가중 평균. 물량 합이 0이면(이론상) NULL 나누기를 피하려고 NULLIF
  CAST(SUM(price_per_kg * volume_kg) / NULLIF(SUM(volume_kg), 0) AS DECIMAL(10, 1)) AS avg_price,
  MIN(price_per_kg)                       AS min_price,
  MAX(price_per_kg)                       AS max_price,
  CAST(SUM(volume_kg) AS DECIMAL(12, 1))  AS volume_kg,
  CAST(COUNT(*) AS INT)                   AS trade_count,
  MAX(auction_at)                         AS last_auction_at,
  CAST(LOCALTIMESTAMP AS TIMESTAMP(0))    AS updated_at
FROM (
  SELECT COALESCE(TRY_CAST(settle_ymd AS DATE), CAST(auction_at + INTERVAL '9' HOUR AS DATE)) AS trade_date,
         market_id, item_id, price_per_kg, volume_kg, auction_at
  FROM auction_dedup
  -- 물량이 0이거나 음수인 건(취소·정정으로 보이는 건, 2026-11-18 서울강서·인천남촌 등에서 나옴)은 뺀다.
  -- 그런 건이 먼저 오면 물량 합이 0이라 avg_price가 NULL이 되고, NOT NULL 컬럼이라 작업 전체가 멈춘다
  WHERE volume_kg > 0
)
GROUP BY trade_date, market_id, item_id;
