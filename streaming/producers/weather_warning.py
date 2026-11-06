"""기상특보 수집기: 기상청 특보코드조회(getPwnCd) → Kafka weather.warning.raw (REQ-COL-004)

특보 1건(발표 시각 × 구역 × 종류 × 단계)을 메시지 1개로 보낸다.
저장과 중복 방지는 Flink(streaming/flink/weather_warning.sql)가 source_key 기준으로 한다.
그래서 같은 기간을 여러 번 수집해도 MySQL에는 한 번만 남는다.

실행 (레포 루트에서):
    streaming/.venv/Scripts/python streaming/producers/weather_warning.py            # Windows
    streaming/.venv/bin/python streaming/producers/weather_warning.py                # WSL·Linux
    ... weather_warning.py --dry-run     # Kafka에 보내지 않고 변환 결과만 출력
    ... weather_warning.py --every 600   # 10분마다 계속 (compose의 weather-warning-producer가 이렇게 돈다)
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from confluent_kafka import Producer
from dotenv import load_dotenv

API_URL = 'https://apis.data.go.kr/1360000/WthrWrnInfoService/getPwnCd'
TOPIC = 'weather.warning.raw'
KST = timezone(timedelta(hours=9))
PAGE_SIZE = 1000
# API가 최근 6일치만 보장하므로 오늘 포함 6일을 요청한다
DEFAULT_DAYS = 6

# 코드표: 기상청 기상특보 조회서비스 활용가이드 "9) 특보코드조회" 응답 명세 기준.
# 실제 응답의 1·2·3·6(종류), 1·2·3·7(발표코드)은 같은 시각 특보 목록(getWthrWrnList) 제목과도 맞대어 확인했다
WARN_VAR = {
    1: '강풍', 2: '호우', 3: '한파', 4: '건조', 5: '폭풍해일', 6: '풍랑',
    7: '태풍', 8: '대설', 9: '황사', 12: '폭염', 13: '열대야',  # 13은 '26.6.1.부터
}
WARN_STRESS = {0: '주의보', 1: '경보', 2: '중대경보'}
COMMAND = {'1': '발표', '2': '해제', '3': '연장', '6': '정정', '7': '변경발표', '8': '변경해제'}
# cancel=1(취소된 특보)은 status를 '취소'로 저장한다. source_key에 cancel이 없으므로
# 이미 저장된 특보가 나중에 취소로 오면 같은 행이 '취소'로 덮어써진다. 알림은 '취소'를 제외해야 한다
CANCELED = '취소'


def fetch_items(service_key, from_date, to_date):
    """기간 안의 특보를 모든 페이지에서 모은다.

    응답의 totalCount는 실제 행 수와 맞지 않아서(154라고 하고 590행을 준다) 믿지 않는다.
    빈 페이지(resultCode 03 NO_DATA)가 나오거나 한 페이지가 덜 찰 때까지 넘긴다.
    """
    items, page = [], 1
    while True:
        body = call_api(service_key, from_date, to_date, page)
        if body is None:
            break
        rows = body['items']['item']
        items.extend(rows)
        if len(rows) < PAGE_SIZE:
            break
        page += 1
    return items, page


# 활용가이드 "Open API 에러 코드" 중 다시 시도하면 될 수 있는 서버 쪽 일시 오류.
# 나머지(10~12 파라미터, 20~22 접근·한도, 30~33 키·IP)는 재시도해도 같으므로 바로 멈춘다
RETRYABLE_CODES = {'01', '02', '04', '05', '99'}


class ApiError(RuntimeError):
    def __init__(self, code, msg):
        super().__init__(f'API 오류 {code}: {msg}')
        self.code = code


def parse_result(res):
    """응답에서 (결과 코드, 메시지, body)를 꺼낸다. 형식이 두 가지다.

    - 정상·자료 없음 등: {"response": {"header": {resultCode, resultMsg}, "body": ...}}
    - 키·접근 오류: HTTP 403 등과 함께 {"OpenAPI_ServiceResponse": {"cmmMsgHeader": {returnReasonCode, ...}}}
    """
    data = res.json()
    if 'response' in data:
        header = data['response']['header']
        return header['resultCode'], header['resultMsg'], data['response'].get('body')
    head = data['OpenAPI_ServiceResponse']['cmmMsgHeader']
    return head['returnReasonCode'].zfill(2), f"{head.get('errMsg')} ({head.get('returnAuthMsg')})", None


def call_api(service_key, from_date, to_date, page, retries=3):
    params = {
        'serviceKey': service_key, 'dataType': 'JSON', 'numOfRows': PAGE_SIZE, 'pageNo': page,
        'fromTmFc': from_date.strftime('%Y%m%d'), 'toTmFc': to_date.strftime('%Y%m%d'),
    }
    for attempt in range(1, retries + 1):
        try:
            res = requests.get(API_URL, params=params, timeout=30)
            try:
                code, msg, body = parse_result(res)
            except (ValueError, KeyError):
                # 예상한 JSON이 아니면(게이트웨이 장애 HTML 등) 상태 코드로 판단한다
                res.raise_for_status()
                raise ApiError('99', f'알 수 없는 응답: {res.text[:200]}')
            if code == '00':
                return body
            if code == '03':  # NODATA: 기간에 특보가 없거나 마지막 페이지를 넘었다
                return None
            raise ApiError(code, msg)
        except ApiError as e:
            if e.code not in RETRYABLE_CODES or attempt == retries:
                raise
        except requests.RequestException as e:  # 연결 실패·시간 초과·5xx
            if attempt == retries:
                raise RuntimeError(f'API 호출 실패 (page {page}): {e}') from e
        time.sleep(2 * attempt)


def kst_to_utc_iso(value):
    """API 시각(KST, YYYYMMDDHHMM 숫자) → UTC ISO 문자열. 값이 없으면(0) None"""
    if not value or str(value) == '0':
        return None
    kst = datetime.strptime(str(value), '%Y%m%d%H%M').replace(tzinfo=KST)
    return kst.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S')


def to_message(item):
    """API 행 1개 → Kafka 메시지(dict). ERD weather_warning 컬럼과 이름을 맞춘다.
    effective_at·ended_at은 weather_warning에는 저장하지 않고 알림(special_event.detail)에서 쓴다."""
    tm_fc = str(item['tmFc'])  # 발표 시각, KST, YYYYMMDDHHMM
    var, stress, command = int(item['warnVar']), int(item['warnStress']), str(item['command'])
    return {
        # 발표 시각(API 원래 값) + 구역 + 종류 + 단계. API 값 그대로라 원본과 대조하기 쉽다
        'source_key': f"{tm_fc}_{item['areaCode']}_{var}_{stress}",
        # DB는 UTC로 저장한다 (backend/config/settings.py 시간 규칙)
        'announced_at': kst_to_utc_iso(tm_fc),
        'region_code': item['areaCode'],
        'region_name': item['areaName'],
        # 모르는 코드는 버리지 않고 코드값을 남긴다 (나중에 코드표를 보고 고칠 수 있게)
        'warning_type': WARN_VAR.get(var, f'코드{var}'),
        'level': WARN_STRESS.get(stress, f'코드{stress}'),
        'status': CANCELED if str(item.get('cancel')) == '1' else COMMAND.get(command, f'코드{command}'),
        'effective_at': kst_to_utc_iso(item.get('startTime')),  # 발효 시각 (발표 때만 있음)
        'ended_at': kst_to_utc_iso(item.get('endTime')),        # 해제 시각 (해제 때만 있음)
    }


def collect_once(service_key, days, producer=None):
    """한 번 수집해서 보낸다. producer가 None이면(--dry-run) 보내지 않고 출력만 한다."""
    today = datetime.now(KST).date()
    from_date = today - timedelta(days=days - 1)
    items, pages = fetch_items(service_key, from_date, today)

    # API가 똑같은 행을 두 번 주는 경우가 있어 보내기 전에 한 번 거른다 (최종 중복 방지는 DB)
    messages = {}
    for item in items:
        msg = to_message(item)
        messages[msg['source_key']] = msg
    log(f'{from_date}~{today}: API {len(items)}행 ({pages}페이지) → 특보 {len(messages)}건')

    if producer is None:
        for msg in list(messages.values())[:5]:
            print(json.dumps(msg, ensure_ascii=False))
        return

    failed = []

    def on_delivery(err, msg):
        if err is not None:
            failed.append(err)

    for key, msg in messages.items():
        producer.produce(TOPIC, key=key.encode(), value=json.dumps(msg, ensure_ascii=False).encode(),
                         on_delivery=on_delivery)
        producer.poll(0)
    remaining = producer.flush(30)
    if failed or remaining:
        raise RuntimeError(f'전송 실패 {len(failed)}건, 미전송 {remaining}건: {failed[:3]}')
    log(f'{TOPIC}에 {len(messages)}건 전송 완료')


def log(msg):
    print(f"[{datetime.now(KST):%Y-%m-%d %H:%M:%S}] {msg}", flush=True)


def main():
    parser = argparse.ArgumentParser(description='기상특보 → Kafka')
    parser.add_argument('--days', type=int, default=DEFAULT_DAYS, help='오늘 포함 며칠치 (기본 6)')
    parser.add_argument('--every', type=int, default=0, metavar='SECONDS',
                        help='이 간격(초)으로 계속 반복한다. 0이면 한 번만 (기본 0, compose에서는 600)')
    parser.add_argument('--dry-run', action='store_true', help='Kafka에 보내지 않고 출력만')
    args = parser.parse_args()

    load_dotenv(Path(__file__).resolve().parents[2] / '.env')  # 컨테이너에서는 env_file로 이미 들어와 있다
    service_key = os.environ['DATA_GO_KR_KEY']
    bootstrap = os.environ.get('KAFKA_BOOTSTRAP_SERVERS', 'localhost:29092')

    producer = None if args.dry_run else Producer({
        'bootstrap.servers': bootstrap,
        'acks': 'all',
        'enable.idempotence': True,  # 재전송 때 브로커에 같은 메시지가 두 번 쌓이지 않게
    })

    if args.every <= 0:
        try:
            collect_once(service_key, args.days, producer)
        except Exception as e:
            log(f'실패: {e}')
            sys.exit(1)
        return

    # 반복 모드: 한 번 실패해도 멈추지 않고 다음 주기에 다시 시도한다.
    # 매번 최근 6일치를 받으므로 한두 번 실패해도 다음 성공 때 빠진 특보가 채워진다
    log(f'{args.every}초마다 수집 시작 (Kafka {bootstrap})')
    while True:
        started = time.monotonic()
        try:
            collect_once(service_key, args.days, producer)
        except Exception as e:
            log(f'실패, 다음 주기에 다시 시도: {e}')
        time.sleep(max(0, args.every - (time.monotonic() - started)))


if __name__ == '__main__':
    main()
