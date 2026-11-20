"""당일 경매가 지연 측정 (REQ-NFR-003). 구간 설명은 prices/latency.py 참고.

    # 오늘(정산일자) 수집 기록으로 ①② 확인 + 탐침 5개로 ③ 측정 → 최악 지연 계산
    docker compose -f infra/docker-compose.yml exec -e KAFKA_BOOTSTRAP_SERVERS=kafka:9092 backend \
        python manage.py measure_realtime_latency --probes 5

    --date YYYY-MM-DD   수집 기록을 볼 정산일자 (기본: 오늘 한국 날짜)
    --probes N          탐침 개수 (0이면 ③은 재지 않고 --pipeline-seconds 값을 쓴다)
    --screen-seconds S  화면 갱신 주기 (기본 60초, 프론트 설정과 맞춘다)

탐침: 정산일자 2099-12-31인 가짜 낙찰을 auction.trade.raw에 보내고 realtime_price에 반영될 때까지 잰다.
오늘 화면(API)에는 나오지 않는 날짜이고, 끝나면 realtime_price·auction_trade의 탐침 행을 지운다.
"""
import json
import os
import time
import uuid
from datetime import datetime, timedelta, timezone as dt_timezone
from zoneinfo import ZoneInfo

from django.core.management.base import BaseCommand, CommandError

from api.models import CollectLog
from codes.models import Item, Market
from prices import latency
from prices.models import AuctionTrade, RealtimePrice

KST = ZoneInfo('Asia/Seoul')
TOPIC = 'auction.trade.raw'
SOURCE = 'at_auction'
PROBE_DATE = '2099-12-31'
PROBE_PREFIX = 'probe-'
TIME_FMT = '%Y-%m-%d %H:%M:%S'


class Command(BaseCommand):
    help = '당일 경매가 지연 측정 (수집 주기·수집 소요·Kafka→Flink→MySQL·화면 갱신)'

    def add_arguments(self, parser):
        parser.add_argument('--date', help='정산일자 YYYY-MM-DD (기본: 오늘 한국 날짜)')
        parser.add_argument('--probes', type=int, default=5)
        parser.add_argument('--timeout', type=float, default=60, help='탐침 하나를 기다리는 최대 초')
        parser.add_argument('--poll-seconds', type=float, default=120, help='수집 기록이 없을 때 쓸 수집 주기')
        parser.add_argument('--pipeline-seconds', type=float, default=5, help='--probes 0일 때 쓸 ③ 값')
        parser.add_argument('--screen-seconds', type=float, default=60)

    def handle(self, *args, **opts):
        date = opts['date'] or datetime.now(KST).strftime('%Y-%m-%d')
        poll, collect = self.report_collect(date, opts['poll_seconds'])
        self.report_at_lag(date)

        pipeline = opts['pipeline_seconds']
        if opts['probes'] > 0:
            pipeline = self.run_probes(opts['probes'], opts['timeout'])

        parts, total, ok = latency.worst_case(poll, collect, pipeline, opts['screen_seconds'])
        self.stdout.write('\n[최악 지연] aT API 반영 → 화면')
        for name, sec in parts.items():
            self.stdout.write(f'  {name:<36} {sec:7.1f}초')
        verdict = '통과' if ok else '초과'
        self.stdout.write(f'  {"합계":<36} {total:7.1f}초  (한도 {latency.LIMIT_SECONDS}초) → {verdict}')

    # ── ①② 수집 기록 ──────────────────────────────────────────────
    def report_collect(self, date, default_poll):
        logs = list(CollectLog.objects.filter(source=SOURCE, target_date=date, finished_at__isnull=False)
                    .order_by('started_at'))
        self.stdout.write(f'[수집 기록] 정산일자 {date}, at_auction {len(logs)}회')
        if len(logs) < 2:
            self.stdout.write(f'  기록이 2회 미만이라 수집 주기는 설정값 {default_poll:.0f}초로 계산한다')
        gap = latency.summary(latency.gaps([log.started_at for log in logs]))
        took = latency.summary([(log.finished_at - log.started_at).total_seconds() for log in logs])
        self._line('① 수집 주기', gap)
        self._line('② 수집 소요', took)
        return (gap['max'] or default_poll), (took['max'] or 0)

    # ── 참고: 낙찰 → 우리가 받은 시각 (aT 반영 지연 + ① 대기) ────────────
    def report_at_lag(self, date):
        # 정산일자 D에는 전날 오후 경매분도 있으므로 D-1 0시(KST)부터 본다 (프로듀서와 같은 범위)
        day = datetime.strptime(date, '%Y-%m-%d').replace(tzinfo=KST)
        trades = AuctionTrade.objects.filter(auction_at__gte=day - timedelta(days=1), auction_at__lt=day + timedelta(days=1)) \
            .exclude(source_key__startswith=PROBE_PREFIX).values_list('auction_at', 'collected_at')
        lag = latency.summary([(c - a).total_seconds() for a, c in trades])
        self.stdout.write('[참고] 낙찰 → 수집 (aT 자체 지연 포함, 요구사항 범위 밖)')
        self._line('낙찰→수집', lag)

    # ── ③ 탐침 ──────────────────────────────────────────────────
    def run_probes(self, count, timeout):
        from confluent_kafka import Producer  # 탐침을 쓸 때만 필요

        market = Market.objects.filter(is_collect=True).order_by('market_id').first()
        item = Item.objects.order_by('pk').first()
        if market is None or item is None:
            raise CommandError('market·item 기준 데이터가 없다. loaddata markets_collect items 를 먼저 한다')
        producer = Producer({'bootstrap.servers': os.environ.get('KAFKA_BOOTSTRAP_SERVERS', 'kafka:9092')})
        self.stdout.write(f'[파이프라인 탐침] {count}개, 시장 {market.market_id}·품목 {item.pk}·정산일자 {PROBE_DATE}')

        results = []
        try:
            for i in range(count):
                # 낙찰 시각을 탐침마다 1초 이상 다르게 해 last_auction_at으로 "이번 탐침이 반영됐는지"를 구분한다
                time.sleep(max(0.0, 1.05 - (time.time() % 1)))
                now = datetime.now(dt_timezone.utc).replace(microsecond=0)
                msg = {
                    'source_key': f'{PROBE_PREFIX}{uuid.uuid4().hex}', 'auction_at': now.strftime(TIME_FMT),
                    'market_id': market.market_id, 'item_id': item.pk, 'corp_name': 'PROBE', 'grade': '',
                    'origin': 'PROBE', 'price_per_kg': 1000.0, 'volume_kg': 1.0,
                    'collected_at': now.strftime(TIME_FMT), 'raw': {'trd_clcln_ymd': PROBE_DATE},
                }
                sent = time.monotonic()
                producer.produce(TOPIC, key=market.market_id, value=json.dumps(msg).encode('utf-8'))
                producer.flush(10)
                took = self._wait(market, item, now, sent, timeout)
                if took is None:
                    self.stdout.write(f'  #{i + 1} {timeout:.0f}초 안에 반영되지 않음 (Flink realtime_price 작업이 도는지 확인)')
                    continue
                results.append(took)
                self.stdout.write(f'  #{i + 1} {took:.2f}초')
        finally:
            self._cleanup()

        if not results:
            raise CommandError('탐침이 하나도 반영되지 않았다')
        self._line('③ 파이프라인', latency.summary(results))
        return max(results)

    def _wait(self, market, item, auction_at, start, timeout):
        """보낸 시점(start, monotonic)부터 realtime_price에 이 탐침이 보일 때까지 걸린 초. 시간 안에 안 보이면 None."""
        while time.monotonic() - start < timeout:
            if RealtimePrice.objects.filter(trade_date=PROBE_DATE, market=market, item=item,
                                            last_auction_at__gte=auction_at).exists():
                return time.monotonic() - start
            time.sleep(0.2)
        return None

    def _cleanup(self):
        """탐침이 남긴 행을 지운다 (auction_trade 작업도 같은 토픽을 읽어 탐침을 저장한다).
        auction_trade 쪽은 조금 늦게 쓰일 수 있어 flush 주기(2초)보다 길게 기다린 뒤 지운다."""
        time.sleep(3)
        RealtimePrice.objects.filter(trade_date=PROBE_DATE).delete()
        AuctionTrade.objects.filter(source_key__startswith=PROBE_PREFIX).delete()

    def _line(self, name, s):
        if not s['count']:
            self.stdout.write(f'  {name:<14} 데이터 없음')
            return
        self.stdout.write(f'  {name:<14} {s["count"]}건  중앙값 {s["p50"]:.1f}초  p90 {s["p90"]:.1f}초  최대 {s["max"]:.1f}초')
