"""실시간 경매 프로듀서 (REQ-COL-002).

한국 시간 00~12시에 3분마다, 12~17시에 30분마다 수집 대상 시장(market.is_collect 또는 is_reference)의
새 낙찰 건을 받아 Kafka 토픽에 보낸다. 실행 결과는 collect_log에 남긴다.

    python producer.py                      # 계속 실행 (3분 주기, POLL_SECONDS로 바꾼다)
    python producer.py --once --date 2026-11-06   # 그 날짜를 한 번만 수집 (시간 제한 없음, 테스트·누락 보충용)
"""
import argparse
import collections
import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone

import pymysql
from confluent_kafka import Producer

from client import PAGE_SIZE, AuctionClient
from transform import (
    KST, TIME_FMT, at_code, is_collect_time, new_item, overlap_start, rows_until, source_key, to_message,
)

log = logging.getLogger("auction")
SOURCE = "at_auction"
# 자동 등록 품목의 item_id 시작 번호. items.json(초기 데이터)이 pk를 직접 적으므로 번호가 겹치지 않게 띄운다.
# 겹치면 loaddata가 그 번호의 품목을 다른 품목으로 덮어써 가격이 엉뚱한 이름으로 보인다
AUTO_ITEM_ID_START = 10000


class LimitReached(Exception):
    """오늘 API 호출이 한도에 닿았다."""


def connect_db():
    return pymysql.connect(
        host=os.environ.get("DB_HOST", "mysql"), port=int(os.environ.get("DB_PORT", "3306")),
        user=os.environ["MYSQL_USER"], password=os.environ["MYSQL_PASSWORD"],
        database=os.environ["MYSQL_DATABASE"], charset="utf8mb4", autocommit=True,
    )


def query(conn, sql, args=()):
    with conn.cursor() as cur:
        cur.execute(sql, args)
        return cur.fetchall()


class State:
    """하루 동안 유지하는 상태. 날짜가 바뀌면 새로 만든다."""

    def __init__(self, conn, date):
        self.date = date
        self.last_seen = {}  # 시장별로 지금까지 본 가장 최근 낙찰 일시
        # 이미 보낸 건(재시작해도 다시 보내지 않게 DB에 저장된 건으로 채운다).
        # 정산일자 D의 거래는 전날(D-1) 오후 경매부터 들어 있으므로 전날 0시(KST)부터 읽는다
        day = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=KST).astimezone(timezone.utc)
        rows = query(conn, "SELECT source_key FROM auction_trade WHERE auction_at >= %s AND auction_at < %s",
                     ((day - timedelta(days=1)).strftime(TIME_FMT), (day + timedelta(days=1)).strftime(TIME_FMT)))
        self.sent = {r[0] for r in rows}
        # 오늘(한국 날짜) 이미 쓴 API 호출 수. 한도는 실제 호출한 날 기준이므로 수집 대상 날짜가 아니라
        # 실행 시각으로 센다 (다른 날짜를 --once로 받은 호출도 포함). 재시작해도 이어서 센다
        today = datetime.now(KST).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
        self.calls_before = int(query(conn, "SELECT COALESCE(SUM(api_calls), 0) FROM collect_log "
                                            "WHERE source = %s AND started_at >= %s",
                                      (SOURCE, today.strftime(TIME_FMT)))[0][0])


def register_item(conn, row):
    """item 테이블에 없는 품목을 등록하고 item_id를 돌려준다. 이름이 없어 등록할 수 없으면 None.

    예측·저장성 표시는 false로 둔다 (사람이 정하는 값). 같은 at_code가 이미 있으면 그대로 두고 그 번호를 돌려준다.
    """
    item = new_item(row)
    if item is None:
        return None
    query(conn, "INSERT INTO item (item_id, at_code, name, category, is_storable, is_forecast) "
                "SELECT GREATEST(%s, COALESCE(MAX(item_id), 0) + 1), %s, %s, %s, 0, 0 FROM item "
                "ON DUPLICATE KEY UPDATE item_id = item_id",
          (AUTO_ITEM_ID_START, item["at_code"], item["name"], item["category"]))
    item_id = query(conn, "SELECT item_id FROM item WHERE at_code = %s", (item["at_code"],))[0][0]
    log.info("새 품목 등록: %s %s (%s), item_id %d", item["at_code"], item["name"], item["category"], item_id)
    return item_id


def collect_once(conn, producer, client, topic, state, call_limit):
    """수집 대상 시장을 한 바퀴 돌며 새 건을 Kafka로 보내고 collect_log에 한 줄 남긴다."""
    started = datetime.now(timezone.utc)
    markets = [r[0] for r in query(conn, "SELECT market_id FROM market WHERE is_collect OR is_reference ORDER BY market_id")]
    items = dict(query(conn, "SELECT at_code, item_id FROM item"))
    client.calls = 0
    sent, skipped_unit, registered, errors = 0, 0, 0, []
    unknown = collections.Counter()
    collected_at = started.strftime(TIME_FMT)

    for market in markets:
        stop_before = overlap_start(state.last_seen.get(market))
        newest = state.last_seen.get(market)
        page = 1
        try:
            while True:
                if state.calls_before + client.calls >= call_limit:
                    raise LimitReached(f"하루 호출 한도 {call_limit}건에 닿아 멈춤")
                rows = client.fetch(state.date, market, page)
                if rows and (newest is None or rows[0]["scsbd_dt"] > newest):
                    newest = rows[0]["scsbd_dt"]
                kept, reached = rows_until(rows, stop_before)
                for row in kept:
                    key = source_key(row)
                    if key in state.sent:
                        continue
                    item_id = items.get(at_code(row))
                    if item_id is None:
                        # 처음 보는 품목은 item에 등록하고 이어서 보낸다 (REQ-COL-002). Flink가 쓰기 전에 item 행이 있어야 한다
                        item_id = register_item(conn, row)
                        if item_id is None:
                            unknown[f"{at_code(row)}:{row['gds_mclsf_nm']}"] += 1
                            continue
                        items[at_code(row)] = item_id
                        registered += 1
                    msg = to_message(row, item_id, collected_at)
                    if msg is None:
                        skipped_unit += 1
                        continue
                    # 키를 시장 코드로 두면 같은 시장의 메시지는 같은 파티션에 순서대로 들어간다
                    producer.produce(topic, key=market, value=json.dumps(msg, ensure_ascii=False).encode("utf-8"))
                    producer.poll(0)
                    state.sent.add(key)
                    sent += 1
                if reached or len(rows) < PAGE_SIZE:
                    break
                page += 1
            # 끝까지 받은 시장만 기준 시각을 옮긴다. 중간에 실패하면 다음 바퀴에 같은 구간을 다시 받는다
            if newest:
                state.last_seen[market] = newest
        except LimitReached as e:
            errors.append(str(e))
            log.error("%s", e)
            break
        except Exception as e:  # 한 시장이 실패해도 나머지 시장은 계속 받는다
            errors.append(f"{market}: {e}")
            log.error("시장 %s 수집 실패: %s", market, e)

    remaining = producer.flush(30)
    if remaining:
        errors.append(f"Kafka 전송 대기 {remaining}건이 남음")
    state.calls_before += client.calls
    status = "success" if not errors else ("fail" if len(errors) >= len(markets) else "partial")
    query(conn, "INSERT INTO collect_log (source, target_date, started_at, finished_at, status, row_count, api_calls, error_msg) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
          (SOURCE, state.date, started.strftime(TIME_FMT), datetime.now(timezone.utc).strftime(TIME_FMT),
           status, sent, client.calls, "\n".join(errors) or None))
    log.info("%s 전송 %d건, 호출 %d건(오늘 누적 %d), kg 아님 %d건, 새 품목 등록 %d개, 미등록 품목 %d건 %s, 상태 %s",
             state.date, sent, client.calls, state.calls_before, skipped_unit, registered,
             sum(unknown.values()), dict(unknown.most_common(5)), status)
    return status


def main():
    parser = argparse.ArgumentParser(description="실시간 경매 → Kafka 프로듀서")
    parser.add_argument("--once", action="store_true", help="한 번만 수집하고 끝낸다 (시간 제한 없음)")
    parser.add_argument("--date", help="거래정산일자 YYYY-MM-DD (기본: 오늘 한국 날짜)")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    topic = os.environ.get("AUCTION_TOPIC", "auction.trade.raw")  # compose의 kafka-init이 미리 만든다
    # REQ-NFR-003(5분 안 반영)과 하루 한도를 같이 맞추는 주기. 전국 32곳 × 240바퀴(12시간 ÷ 3분) = 7,680건
    # (12~17시는 30분마다 돌아 320건이 더 든다. is_collect_time)
    interval = int(os.environ.get("POLL_SECONDS", "180"))
    call_limit = int(os.environ.get("DAILY_CALL_LIMIT", "9000"))  # 한도 10,000건보다 여유 있게 멈춘다
    client = AuctionClient(os.environ["DATA_GO_KR_KEY"])
    producer = Producer({
        "bootstrap.servers": os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092"),  # 기상특보 수집기와 같은 이름
        "acks": "all",
        "enable.idempotence": True,  # 브로커 재시도로 같은 메시지가 두 번 쓰이지 않게
    })
    conn = connect_db()
    state = None
    last_collected = None  # 지난 수집을 시작한 시각 (오후 30분 주기 판단용)

    while True:
        now = datetime.now(KST)
        date = args.date or now.strftime("%Y-%m-%d")
        if state is None or state.date != date:
            state = State(conn, date)
            log.info("%s 시작: 이미 저장된 건 %d건, 오늘 호출 %d건", date, len(state.sent), state.calls_before)
        if args.once:
            collect_once(conn, producer, client, topic, state, call_limit)
            return
        if is_collect_time(now, last_collected):
            conn.ping(reconnect=True)
            collect_once(conn, producer, client, topic, state, call_limit)
            last_collected = now
        time.sleep(interval - time.time() % interval)  # 주기 경계(2분이면 …:00, …:02)에 맞춰 깬다


if __name__ == "__main__":
    main()
