from datetime import date, datetime, timezone as dt_timezone
from unittest import mock

from django.test import SimpleTestCase, TestCase

from api.models import CollectLog
from codes.models import Item, Market

from . import latency
from .models import RealtimePrice

URL = '/api/prices/realtime'


def utc(*args):
    return datetime(*args, tzinfo=dt_timezone.utc)


class RealtimePriceApiTest(TestCase):
    """GET /api/prices/realtime (REQ-PRC-004)."""

    @classmethod
    def setUpTestData(cls):
        def market(market_id, name, is_collect=True):
            return Market.objects.create(market_id=market_id, name=name, sido='대전', lat=0, lng=0,
                                         is_collect=is_collect)
        cls.m1 = market('250001', '대전오정')
        cls.m2 = market('250003', '대전노은')
        cls.ref = market('110001', '가락', is_collect=False)   # 참고 시장: 기본 목록에 안 나온다
        cls.apple = Item.objects.create(at_code='0601', name='사과', category='과일')
        cls.today = date(2026, 11, 13)
        RealtimePrice.objects.create(
            trade_date=cls.today, market=cls.m1, item=cls.apple,
            avg_price=3420, min_price=1900, max_price=5100, volume_kg=1240, trade_count=37,
            last_auction_at=utc(2026, 11, 12, 23, 42), updated_at=utc(2026, 11, 12, 23, 45))
        # 어제 행은 오늘 응답에 섞이지 않아야 한다
        RealtimePrice.objects.create(
            trade_date=date(2026, 11, 12), market=cls.m2, item=cls.apple,
            avg_price=9999, min_price=9999, max_price=9999, volume_kg=1, trade_count=1,
            last_auction_at=utc(2026, 11, 11, 23, 0), updated_at=utc(2026, 11, 11, 23, 0))

    def log(self, finished_at, status='success', target_date=None):
        return CollectLog.objects.create(source='at_auction', target_date=target_date or self.today,
                                         started_at=finished_at, finished_at=finished_at, status=status)

    def get(self, now, **params):
        with mock.patch('prices.views.timezone.now', return_value=now):
            return self.client.get(URL, params)

    def test_경매_중이면_live와_한국시간(self):
        self.log(utc(2026, 11, 13, 0, 5))
        res = self.get(utc(2026, 11, 13, 0, 10), item_id=self.apple.pk)   # 한국 09:10
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual([r['market_id'] for r in body['data']], ['250001', '250003'])
        row = body['data'][0]
        self.assertEqual(row, {
            'market_id': '250001', 'market_name': '대전오정', 'trade_date': '2026-11-13',
            'avg_price': 3420.0, 'min_price': 1900.0, 'max_price': 5100.0,
            'volume_kg': 1240.0, 'trade_count': 37,
            'last_auction_at': '2026-11-13T08:42:00+09:00', 'status': 'live',
        })
        self.assertEqual(body['meta'], {'collected_at': '2026-11-13T09:05:00+09:00', 'price_unit': '원/kg'})

    def test_거래_없는_시장은_no_trade(self):
        self.log(utc(2026, 11, 13, 0, 5))
        row = self.get(utc(2026, 11, 13, 0, 10), item_id=self.apple.pk).json()['data'][1]
        self.assertEqual(row['status'], 'no_trade')
        self.assertIsNone(row['avg_price'])
        self.assertEqual(row['trade_count'], 0)

    def test_12시_이후는_closed(self):
        self.log(utc(2026, 11, 13, 2, 55))
        res = self.get(utc(2026, 11, 13, 3, 0), item_id=self.apple.pk)   # 한국 12:00
        self.assertEqual(res.json()['data'][0]['status'], 'closed')

    def test_market_id로_한_시장만(self):
        self.log(utc(2026, 11, 13, 0, 5))
        res = self.get(utc(2026, 11, 13, 0, 10), item_id=self.apple.pk, market_id='250003')
        self.assertEqual([r['market_id'] for r in res.json()['data']], ['250003'])

    def test_collected_at은_실패를_빼고_가장_최근(self):
        self.log(utc(2026, 11, 13, 0, 5))
        self.log(utc(2026, 11, 13, 0, 9), status='fail')
        self.log(utc(2026, 11, 12, 2, 0), target_date=date(2026, 11, 12))
        res = self.get(utc(2026, 11, 13, 0, 10), item_id=self.apple.pk)
        self.assertEqual(res.json()['meta']['collected_at'], '2026-11-13T09:05:00+09:00')

    def test_오늘_수집_전이면_503(self):
        self.log(utc(2026, 11, 12, 2, 0), target_date=date(2026, 11, 12))   # 어제 기록만 있음
        res = self.get(utc(2026, 11, 12, 15, 30), item_id=self.apple.pk)    # 한국 11/13 00:30
        self.assertEqual(res.status_code, 503)
        self.assertEqual(res.json()['error']['code'], 'DATA_NOT_READY')

    def test_item_id_검사(self):
        now = utc(2026, 11, 13, 0, 10)
        self.assertEqual(self.get(now).json()['error']['details'], {'item_id': ['필수 값입니다.']})
        self.assertEqual(self.get(now, item_id='abc').status_code, 400)
        res = self.get(now, item_id=999)
        self.assertEqual((res.status_code, res.json()['error']['code']), (404, 'NOT_FOUND'))

    def test_없는_시장은_404(self):
        res = self.get(utc(2026, 11, 13, 0, 10), item_id=self.apple.pk, market_id='999999')
        self.assertEqual(res.status_code, 404)


class LatencyTest(SimpleTestCase):
    """prices/latency.py (REQ-NFR-003 지연 계산)."""

    def test_percentile(self):
        values = [5, 1, 4, 2, 3]
        self.assertEqual(latency.percentile(values, 50), 3)
        self.assertEqual(latency.percentile(values, 90), 5)
        self.assertIsNone(latency.percentile([], 50))

    def test_gaps는_정렬_뒤_간격(self):
        times = [utc(2026, 11, 13, 0, 10), utc(2026, 11, 13, 0, 0), utc(2026, 11, 13, 0, 5)]
        self.assertEqual(latency.gaps(times), [300.0, 300.0])
        self.assertEqual(latency.gaps(times[:1]), [])

    def test_summary_비어_있음(self):
        self.assertEqual(latency.summary([]), {'count': 0, 'p50': None, 'p90': None, 'max': None})

    def test_worst_case_합계와_판정(self):
        _, total, ok = latency.worst_case(300, 20, 3, 60)
        self.assertEqual((total, ok), (383, False))
        _, total, ok = latency.worst_case(120, 20, 3, 60)
        self.assertEqual((total, ok), (203, True))
