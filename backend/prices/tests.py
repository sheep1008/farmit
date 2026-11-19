from datetime import date, datetime, timedelta, timezone as dt_timezone
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

    def test_17시_전은_live_이후는_closed(self):
        self.log(utc(2026, 11, 13, 2, 55))
        res = self.get(utc(2026, 11, 13, 7, 59), item_id=self.apple.pk)   # 한국 16:59
        self.assertEqual(res.json()['data'][0]['status'], 'live')
        res = self.get(utc(2026, 11, 13, 8, 0), item_id=self.apple.pk)   # 한국 17:00
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


# ---------------------------------------------------------------------------
# Y04: 가격 API (markets, items, prices/daily, prices/compare)
# ---------------------------------------------------------------------------
from .models import SettlePrice  # noqa: E402


class PriceApiBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        def market(market_id, name, is_collect=True, is_reference=False):
            return Market.objects.create(market_id=market_id, name=name, sido='대전', lat=0, lng=0,
                                         is_collect=is_collect, is_reference=is_reference)
        cls.m1 = market('250001', '대전오정')
        cls.m2 = market('250003', '대전노은')
        cls.m3 = market('340101', '천안')                       # 거래 없음 → avg_price null
        cls.ref = market('110001', '서울가락', is_collect=False, is_reference=True)
        cls.apple = Item.objects.create(at_code='0601', name='사과', category='과일', is_forecast=True)
        cls.pear = Item.objects.create(at_code='0602', name='배', category='과일')

    def put(self, market, item, day, avg, vol=100, lo=None, hi=None, grade='ALL'):
        return SettlePrice.objects.create(
            trade_date=day, market=market, item=item, grade=grade, avg_price=avg,
            min_price=lo if lo is not None else avg - 100, max_price=hi if hi is not None else avg + 100,
            volume_kg=vol)


class MarketItemApiTest(PriceApiBase):
    """GET /api/markets (REQ-PRC-001), GET /api/items (REQ-SRC-001)."""

    def test_markets_default_returns_collect_markets_and_reference_market(self):
        res = self.client.get('/api/markets')
        self.assertEqual(res.status_code, 200)
        # 수집 대상 3곳 + 참고 시장(가락). api.md 2.2: "4개 + 가락"
        self.assertEqual([m['market_id'] for m in res.json()['data']], ['110001', '250001', '250003', '340101'])
        self.assertEqual(set(res.json()['data'][0]), {'market_id', 'name', 'sido', 'is_reference'})

    def test_markets_search_by_partial_name(self):
        res = self.client.get('/api/markets', {'q': '천'})
        self.assertEqual([m['name'] for m in res.json()['data']], ['천안'])
        # q와 collect를 함께 쓰면 collect=false일 때 참고 시장도 찾는다
        res = self.client.get('/api/markets', {'q': '가락', 'collect': 'false'})
        self.assertEqual([m['market_id'] for m in res.json()['data']], ['110001'])
        self.assertEqual(self.client.get('/api/markets', {'q': '없는시장'}).json()['data'], [])

    def test_markets_collect_false_returns_all(self):
        res = self.client.get('/api/markets', {'collect': 'false'})
        self.assertEqual(len(res.json()['data']), 4)
        self.assertTrue([m for m in res.json()['data'] if m['market_id'] == '110001'][0]['is_reference'])

    def test_markets_invalid_collect_is_400(self):
        res = self.client.get('/api/markets', {'collect': 'maybe'})
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.json()['error']['code'], 'INVALID_PARAMETER')

    def test_items_search_by_partial_name(self):
        res = self.client.get('/api/items', {'q': '사'})
        self.assertEqual([i['name'] for i in res.json()['data']], ['사과'])
        self.assertEqual(set(res.json()['data'][0]),
                         {'item_id', 'name', 'category', 'is_storable', 'is_forecast'})

    def test_items_forecast_filter(self):
        res = self.client.get('/api/items', {'forecast': 'true'})
        self.assertEqual([i['name'] for i in res.json()['data']], ['사과'])

    def test_items_no_match_is_200_empty_list(self):
        res = self.client.get('/api/items', {'q': '없는품목'})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()['data'], [])

    def test_items_invalid_forecast_is_400(self):
        self.assertEqual(self.client.get('/api/items', {'forecast': 'x'}).json()['error']['code'],
                         'INVALID_PARAMETER')


class DailyPriceApiTest(PriceApiBase):
    """GET /api/prices/daily (REQ-PRC-001, REQ-PRC-005)."""
    URL = '/api/prices/daily'

    def get(self, **params):
        base = {'item_id': self.apple.item_id, 'market_id': '250001'}
        base.update(params)
        return self.client.get(self.URL, base)

    def test_day_unit_rows_and_meta(self):
        self.put(self.m1, self.apple, date(2026, 10, 27), 2000, vol=300, lo=1500, hi=2600)
        self.put(self.m1, self.apple, date(2026, 10, 26), 1000, vol=100, lo=800, hi=1200)
        self.put(self.m2, self.apple, date(2026, 10, 26), 9999)            # 다른 시장은 섞이지 않는다
        CollectLog.objects.create(source='at_settle', target_date=date(2026, 10, 27),
                                  started_at=utc(2026, 10, 27, 21, 0), finished_at=utc(2026, 10, 27, 21, 10),
                                  status='success')
        res = self.get(**{'from': '2026-10-26', 'to': '2026-10-27'})
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual([r['period'] for r in body['data']], ['2026-10-26', '2026-10-27'])
        self.assertEqual(body['data'][1], {'period': '2026-10-27', 'avg_price': 2000.0, 'min_price': 1500.0,
                                           'max_price': 2600.0, 'volume_kg': 300.0})
        self.assertEqual(body['meta'], {
            'item_id': self.apple.item_id, 'market_id': '250001', 'unit': 'day', 'grade': 'ALL',
            'price_unit': '원/kg', 'last_updated': '2026-10-28T06:10:00+09:00'})

    def test_week_unit_uses_monday_and_volume_weighted_average(self):
        self.put(self.m1, self.apple, date(2026, 10, 26), 1000, vol=100, lo=800, hi=1200)   # 월
        self.put(self.m1, self.apple, date(2026, 10, 28), 2000, vol=300, lo=1500, hi=2600)  # 수
        self.put(self.m1, self.apple, date(2026, 11, 2), 500, vol=10)                         # 다음 주 월
        res = self.get(unit='week', **{'from': '2026-10-26', 'to': '2026-11-08'})
        rows = res.json()['data']
        self.assertEqual([r['period'] for r in rows], ['2026-10-26', '2026-11-02'])
        # (1000×100 + 2000×300) / 400 = 1750
        self.assertEqual(rows[0], {'period': '2026-10-26', 'avg_price': 1750.0, 'min_price': 800.0,
                                   'max_price': 2600.0, 'volume_kg': 400.0})

    def test_month_unit_period_is_year_month(self):
        self.put(self.m1, self.apple, date(2026, 9, 30), 1000, vol=100)
        self.put(self.m1, self.apple, date(2026, 10, 1), 3000, vol=100)
        self.put(self.m1, self.apple, date(2026, 10, 31), 1000, vol=300)
        res = self.get(unit='month', **{'from': '2026-09-01', 'to': '2026-10-31'})
        rows = res.json()['data']
        self.assertEqual([r['period'] for r in rows], ['2026-09', '2026-10'])
        self.assertEqual(rows[1]['avg_price'], 1500.0)             # (3000×100 + 1000×300) / 400

    def test_grade_filter_returns_only_that_grade(self):
        self.put(self.m1, self.apple, date(2026, 10, 26), 1000)
        self.put(self.m1, self.apple, date(2026, 10, 26), 1800, grade='특')
        all_rows = self.get(**{'from': '2026-10-26', 'to': '2026-10-26'}).json()['data']
        special = self.get(grade='특', **{'from': '2026-10-26', 'to': '2026-10-26'})
        self.assertEqual([r['avg_price'] for r in all_rows], [1000.0])
        self.assertEqual([r['avg_price'] for r in special.json()['data']], [1800.0])
        self.assertEqual(special.json()['meta']['grade'], '특')

    def test_compare_last_year_adds_field_only_when_requested(self):
        self.put(self.m1, self.apple, date(2026, 10, 26), 1000)
        self.put(self.m1, self.apple, date(2025, 10, 26), 800)
        params = {'from': '2026-10-26', 'to': '2026-10-26'}
        with_flag = self.get(compare_last_year='true', **params).json()['data'][0]
        without = self.get(**params).json()['data'][0]
        self.assertEqual(with_flag['last_year_avg_price'], 800.0)
        self.assertNotIn('last_year_avg_price', without)

    def test_compare_last_year_week_aligns_52_weeks_back(self):
        self.put(self.m1, self.apple, date(2026, 10, 26), 1000)    # 월요일
        self.put(self.m1, self.apple, date(2025, 10, 27), 700)     # 364일 전 = 작년 월요일
        res = self.get(unit='week', compare_last_year='true', **{'from': '2026-10-26', 'to': '2026-11-01'})
        self.assertEqual(res.json()['data'][0]['last_year_avg_price'], 700.0)

    def test_compare_last_year_is_null_when_no_data_last_year(self):
        self.put(self.m1, self.apple, date(2026, 10, 26), 1000)
        res = self.get(compare_last_year='true', **{'from': '2026-10-26', 'to': '2026-10-26'})
        self.assertIsNone(res.json()['data'][0]['last_year_avg_price'])

    def test_no_trade_days_have_no_row_and_empty_result_is_200(self):
        res = self.get(**{'from': '2026-10-26', 'to': '2026-10-27'})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()['data'], [])
        self.assertIsNone(res.json()['meta']['last_updated'])

    def test_default_range_is_last_90_days_until_yesterday(self):
        self.put(self.m1, self.apple, date(2026, 8, 4), 1)     # 90일보다 이전
        self.put(self.m1, self.apple, date(2026, 8, 5), 2)     # 오늘(11-03) − 90일
        self.put(self.m1, self.apple, date(2026, 11, 2), 3)    # 어제
        self.put(self.m1, self.apple, date(2026, 11, 3), 4)    # 오늘은 정산 전이라 제외
        with mock.patch('prices.views._today_kst', return_value=date(2026, 11, 3)):
            res = self.get()
        self.assertEqual([r['avg_price'] for r in res.json()['data']], [2.0, 3.0])

    def test_required_params_missing_is_400_with_details(self):
        res = self.client.get(self.URL)
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.json()['error']['code'], 'VALIDATION_ERROR')
        self.assertEqual(set(res.json()['error']['details']), {'item_id', 'market_id'})

    def test_bad_date_format_is_400(self):
        res = self.get(**{'from': '2026/10/26'})
        self.assertEqual((res.status_code, res.json()['error']['code']), (400, 'VALIDATION_ERROR'))
        self.assertIn('from', res.json()['error']['details'])

    def test_from_after_to_is_400(self):
        res = self.get(**{'from': '2026-10-27', 'to': '2026-10-26'})
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.json()['error']['code'], 'VALIDATION_ERROR')

    def test_range_limits_per_unit(self):
        over_year = {'from': '2025-10-01', 'to': '2026-10-02'}           # 367일
        res = self.get(**over_year)
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.json()['error']['code'], 'VALIDATION_ERROR')
        self.assertEqual(self.get(unit='week', **over_year).status_code, 200)
        over_five_years = {'from': '2020-01-01', 'to': '2026-01-01'}
        self.assertEqual(self.get(unit='month', **over_five_years).status_code, 400)

    def test_range_limit_counts_years_not_days_so_leap_day_is_ok(self):
        # 정확히 1년·5년은 윤일이 끼어도 통과하고, 하루라도 넘으면 거절된다
        self.assertEqual(self.get(**{'from': '2027-03-01', 'to': '2028-02-29'}).status_code, 200)
        self.assertEqual(self.get(**{'from': '2027-03-01', 'to': '2028-03-01'}).status_code, 200)
        self.assertEqual(self.get(**{'from': '2027-03-01', 'to': '2028-03-02'}).status_code, 400)
        five = {'unit': 'month', 'from': '2021-11-15'}
        self.assertEqual(self.get(to='2026-11-14', **five).status_code, 200)          # 1826일
        self.assertEqual(self.get(to='2026-11-15', **five).status_code, 200)
        self.assertEqual(self.get(to='2026-11-16', **five).status_code, 400)

    def test_dates_outside_supported_years_are_400_not_500(self):
        for params in ({'from': '0001-01-01', 'to': '0001-01-02', 'compare_last_year': 'true'},
                       {'from': '2100-12-30', 'to': '9999-12-31', 'unit': 'week', 'compare_last_year': 'true'}):
            res = self.get(**params)
            self.assertEqual((res.status_code, res.json()['error']['code']), (400, 'VALIDATION_ERROR'))

    def test_weighted_average_is_rounded_to_one_decimal(self):
        self.put(self.m1, self.apple, date(2026, 10, 26), 1000, vol=100)
        self.put(self.m1, self.apple, date(2026, 10, 27), 2000, vol=200)
        res = self.get(unit='week', **{'from': '2026-10-26', 'to': '2026-11-01'})
        self.assertEqual(res.json()['data'][0]['avg_price'], 1666.7)       # 1666.666…

    def test_rounding_is_half_up_not_bankers(self):
        # (1000.0×1 + 1000.1×1) / 2 = 1000.05 → 1000.1 (파이썬 round()는 1000.0이 된다)
        self.put(self.m1, self.apple, date(2026, 10, 26), 1000.0, vol=1)
        self.put(self.m1, self.apple, date(2026, 10, 27), 1000.1, vol=1)
        res = self.get(unit='week', **{'from': '2026-10-26', 'to': '2026-11-01'})
        self.assertEqual(res.json()['data'][0]['avg_price'], 1000.1)

    def test_month_unit_with_last_year_comparison(self):
        self.put(self.m1, self.apple, date(2026, 10, 5), 1500, vol=100)
        self.put(self.m1, self.apple, date(2025, 10, 20), 900, vol=100)
        res = self.get(unit='month', compare_last_year='true', **{'from': '2026-10-01', 'to': '2026-10-31'})
        self.assertEqual(res.json()['data'][0]['last_year_avg_price'], 900.0)

    def test_invalid_unit_is_400_invalid_parameter(self):
        res = self.get(unit='year')
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.json()['error']['code'], 'INVALID_PARAMETER')

    def test_unknown_item_or_market_is_404(self):
        for res in (self.get(item_id=99999), self.get(market_id='999999')):
            self.assertEqual(res.status_code, 404)
            self.assertEqual(res.json()['error']['code'], 'NOT_FOUND')
        res = self.get(item_id='abc')
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.json()['error']['code'], 'VALIDATION_ERROR')

    def test_query_count_is_constant_regardless_of_row_count(self):
        for day in range(1, 29):
            self.put(self.m1, self.apple, date(2026, 10, day), 1000 + day)
        params = {'from': '2026-10-01', 'to': '2026-10-28', 'compare_last_year': 'true'}
        with self.assertNumQueries(5):          # 품목, 시장, 집계, 전년 집계, 수집 로그
            self.get(**params)
        with self.assertNumQueries(5):
            self.get(unit='week', **params)


class ComparePriceApiTest(PriceApiBase):
    """GET /api/prices/compare (REQ-PRC-003)."""
    URL = '/api/prices/compare'

    def get(self, **params):
        base = {'item_id': self.apple.item_id}
        base.update(params)
        return self.client.get(self.URL, base)

    def test_lists_every_collect_market_with_null_for_no_trade(self):
        self.put(self.m1, self.apple, date(2026, 10, 30), 3507, vol=2310)
        self.put(self.m2, self.apple, date(2026, 10, 30), 3763, vol=1820)
        self.put(self.ref, self.apple, date(2026, 10, 30), 4000)          # 수집 대상이 아닌 시장은 제외
        both = Market.objects.create(market_id='999001', name='수집겸참고', sido='서울', lat=0, lng=0,
                                     is_collect=True, is_reference=True)     # 가락처럼 참고 시장이어도 수집 대상이면 넣는다
        self.put(both, self.apple, date(2026, 10, 30), 4100)
        res = self.get(date='2026-10-30')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()['data'], [
            {'market_id': '250001', 'market_name': '대전오정', 'avg_price': 3507.0, 'volume_kg': 2310.0},
            {'market_id': '250003', 'market_name': '대전노은', 'avg_price': 3763.0, 'volume_kg': 1820.0},
            {'market_id': '340101', 'market_name': '천안', 'avg_price': None, 'volume_kg': 0},
            {'market_id': '999001', 'market_name': '수집겸참고', 'avg_price': 4100.0, 'volume_kg': 100.0},
        ])
        self.assertEqual(res.json()['meta'], {'item_id': self.apple.item_id, 'date': '2026-10-30',
                                              'grade': 'ALL', 'price_unit': '원/kg'})

    def test_default_date_is_latest_settle_date(self):
        self.put(self.m1, self.apple, date(2026, 10, 29), 1000)
        self.put(self.m1, self.apple, date(2026, 10, 30), 2000)
        self.put(self.m1, self.pear, date(2026, 11, 5), 7777)             # 다른 품목의 날짜는 무관
        res = self.get()
        self.assertEqual(res.json()['meta']['date'], '2026-10-30')
        self.assertEqual(res.json()['data'][0]['avg_price'], 2000.0)

    def test_grade_filter(self):
        self.put(self.m1, self.apple, date(2026, 10, 30), 1000)
        self.put(self.m1, self.apple, date(2026, 10, 30), 1800, grade='특')
        res = self.get(date='2026-10-30', grade='특')
        self.assertEqual(res.json()['data'][0]['avg_price'], 1800.0)
        self.assertIsNone(res.json()['data'][1]['avg_price'])

    def test_no_data_at_all_returns_rows_with_null_and_null_date(self):
        res = self.get()
        self.assertEqual(res.status_code, 200)
        self.assertIsNone(res.json()['meta']['date'])
        self.assertTrue(all(r['avg_price'] is None for r in res.json()['data']))

    def test_validation_and_not_found(self):
        res = self.client.get(self.URL)
        self.assertEqual((res.status_code, res.json()['error']['code']), (400, 'VALIDATION_ERROR'))
        self.assertIn('item_id', res.json()['error']['details'])
        for bad in (self.get(item_id='abc'), self.get(date='10-30')):
            self.assertEqual((bad.status_code, bad.json()['error']['code']), (400, 'VALIDATION_ERROR'))
        res = self.get(item_id=99999)
        self.assertEqual((res.status_code, res.json()['error']['code']), (404, 'NOT_FOUND'))

    def test_query_count(self):
        self.put(self.m1, self.apple, date(2026, 10, 30), 1000)
        with self.assertNumQueries(4):          # 품목, 시장 목록, 최근 정산일, 가격
            self.get()


# ---------------------------------------------------------------------------
# 주간 예측 조회, 판매 추천 (Y08: REQ-PRD-001~003, REQ-REC-001~003, REQ-REC-005)
# ---------------------------------------------------------------------------
from decimal import Decimal  # noqa: E402

from django.contrib.auth import get_user_model  # noqa: E402
from django.test import Client  # noqa: E402

from accounts.models import UserProfile  # noqa: E402
from codes.models import Holiday, MarketClosure  # noqa: E402

from .models import Forecast  # noqa: E402

FORECAST_URL = '/api/forecasts'
RECOMMEND_URL = '/api/recommendations'
BASE = date(2026, 11, 9)       # 월요일


def make_forecasts(item, markets, base_week=BASE, price=3000, version='v3'):
    for market in markets:
        for h in range(1, 5):
            Forecast.objects.create(
                item=item, market=market, base_week=base_week, horizon=h,
                target_week=base_week + timedelta(weeks=h - 1),
                pred_price=Decimal(price + h * 100), lower80=Decimal(price + h * 100 - 300),
                upper80=Decimal(price + h * 100 + 300), last_week_price=Decimal(price),
                model_version=version, created_at=utc(2026, 11, 9, 1, 0))



class ForecastApiTest(TestCase):
    """GET /api/forecasts (REQ-PRD-001~003, REQ-PRD-005)."""

    @classmethod
    def setUpTestData(cls):
        cls.m1 = Market.objects.create(market_id='250001', name='대전오정', sido='대전', lat=36.4, lng=127.4,
                                       is_collect=True)
        cls.m2 = Market.objects.create(market_id='340101', name='천안', sido='충남', lat=36.8, lng=127.1,
                                       is_collect=True)
        cls.apple = Item.objects.create(at_code='0601', name='사과', category='과일', is_forecast=True)
        cls.cabbage = Item.objects.create(at_code='1101', name='배추', category='채소', is_forecast=False)
        make_forecasts(cls.apple, [cls.m1, cls.m2])

    def test_시장_4곳_아닌_2곳_x_h4_8행과_구간(self):
        res = self.client.get(FORECAST_URL, {'item_id': self.apple.pk})
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(len(body['data']), 8)
        row = body['data'][0]
        self.assertEqual((row['market_id'], row['horizon'], row['target_week']), ('250001', 1, '2026-11-09'))
        self.assertEqual((row['pred_price'], row['lower80'], row['upper80']), (3100.0, 2800.0, 3400.0))
        self.assertEqual(body['meta']['base_week'], '2026-11-09')
        self.assertEqual(body['meta']['model_version'], 'v3')
        self.assertTrue(body['meta']['forecast_available'])

    def test_예측값은_한국시간_생성시각(self):
        meta = self.client.get(FORECAST_URL, {'item_id': self.apple.pk}).json()['meta']
        self.assertEqual(meta['created_at'], '2026-11-09T10:00:00+09:00')

    def test_시장_필터(self):
        res = self.client.get(FORECAST_URL, {'item_id': self.apple.pk, 'market_id': '340101'})
        self.assertEqual({r['market_id'] for r in res.json()['data']}, {'340101'})

    def test_가장_최근_기준주만_보여_주고_지난_예측은_남아_있다(self):
        make_forecasts(self.apple, [self.m1], base_week=date(2026, 11, 2), price=1000, version='v2')
        res = self.client.get(FORECAST_URL, {'item_id': self.apple.pk})
        self.assertEqual({r['target_week'] for r in res.json()['data']} & {'2026-11-02'}, set())
        self.assertEqual(res.json()['meta']['base_week'], '2026-11-09')
        self.assertEqual(Forecast.objects.filter(base_week=date(2026, 11, 2)).count(), 4)

    def test_명절_3주_이내이면_주의_문구(self):
        Holiday.objects.create(holiday_date=date(2026, 11, 30), name='추석')   # 가정: h1(11/9)은 3주(21일) 이내
        data = self.client.get(FORECAST_URL, {'item_id': self.apple.pk, 'market_id': '250001'}).json()['data']
        notices = {r['horizon']: r['holiday_notice'] for r in data}
        # h1 주(11/9~15)는 11/30까지 15일 → 문구 있음. 모든 h가 21일 안
        self.assertIsNotNone(notices[1])
        self.assertIsNotNone(notices[4])

    def test_명절_멀면_문구_없음_공휴일은_무시(self):
        Holiday.objects.create(holiday_date=date(2026, 12, 25), name='성탄절')
        Holiday.objects.create(holiday_date=date(2027, 9, 15), name='추석')
        data = self.client.get(FORECAST_URL, {'item_id': self.apple.pk}).json()['data']
        self.assertTrue(all(r['holiday_notice'] is None for r in data))

    def test_예측_대상_아닌_품목은_200_forecast_available_false(self):
        res = self.client.get(FORECAST_URL, {'item_id': self.cabbage.pk})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()['data'], [])
        self.assertFalse(res.json()['meta']['forecast_available'])

    def test_예측이_아직_없으면_503(self):
        Forecast.objects.all().delete()
        res = self.client.get(FORECAST_URL, {'item_id': self.apple.pk})
        self.assertEqual((res.status_code, res.json()['error']['code']), (503, 'DATA_NOT_READY'))

    def test_입력_오류(self):
        self.assertEqual(self.client.get(FORECAST_URL).status_code, 400)
        self.assertEqual(self.client.get(FORECAST_URL, {'item_id': '²'}).status_code, 400)
        res = self.client.get(FORECAST_URL, {'item_id': 9999})
        self.assertEqual((res.status_code, res.json()['error']['code']), (404, 'NOT_FOUND'))
        res = self.client.get(FORECAST_URL, {'item_id': self.apple.pk, 'market_id': 'x'})
        self.assertEqual((res.status_code, res.json()['error']['code']), (404, 'NOT_FOUND'))
        res = self.client.get(FORECAST_URL)
        self.assertEqual(res.json()['error']['code'], 'VALIDATION_ERROR')

    def test_이번_주_예측이_아니면_is_stale(self):
        with mock.patch('prices.forecast_views._today_kst', return_value=date(2026, 11, 12)):
            self.assertFalse(self.client.get(FORECAST_URL, {'item_id': self.apple.pk}).json()['meta']['is_stale'])
        with mock.patch('prices.forecast_views._today_kst', return_value=date(2026, 11, 17)):
            self.assertTrue(self.client.get(FORECAST_URL, {'item_id': self.apple.pk}).json()['meta']['is_stale'])

    def test_예측이_없는_시장은_200_빈_배열(self):
        ref = Market.objects.create(market_id='110001', name='가락', sido='서울', lat=0, lng=0)
        res = self.client.get(FORECAST_URL, {'item_id': self.apple.pk, 'market_id': ref.pk})
        self.assertEqual((res.status_code, res.json()['data']), (200, []))

    def test_명절_21일_경계(self):
        # h1 주는 11/9~15. 일요일(15)+21일 = 12/6 은 문구 있음, 12/7 은 h1 기준 없음
        Holiday.objects.create(holiday_date=date(2026, 12, 7), name='설날')
        data = self.client.get(FORECAST_URL, {'item_id': self.apple.pk, 'market_id': '250001'}).json()['data']
        notices = {r['horizon']: r['holiday_notice'] for r in data}
        self.assertIsNone(notices[1])
        self.assertIsNotNone(notices[2])


class RecommendationApiTest(TestCase):
    """POST /api/recommendations (REQ-REC-001~003, REQ-REC-005)."""

    @classmethod
    def setUpTestData(cls):
        # 위도 0, 경도 0 / 1° 차이 = 약 111.19km로 거리를 쉽게 맞춘다
        cls.near = Market.objects.create(market_id='250001', name='가까운시장', sido='대전', lat=0, lng=0,
                                         is_collect=True)
        cls.far = Market.objects.create(market_id='340101', name='먼시장', sido='충남', lat=0, lng=1,
                                        is_collect=True)
        cls.apple = Item.objects.create(at_code='0601', name='사과', category='과일', is_forecast=True)
        cls.cabbage = Item.objects.create(at_code='1101', name='배추', category='채소', is_forecast=False)
        make_forecasts(cls.apple, [cls.near])
        # 먼 시장은 예측가가 500원 더 높다
        make_forecasts(cls.apple, [cls.far], price=3500)
        cls.user = get_user_model().objects.create_user('farmer', password='pw12345678')
        cls.profile = UserProfile.objects.create(user=cls.user, sido='대전', sigungu='서구', lat=0, lng=0)

    def setUp(self):
        self.client = Client(enforce_csrf_checks=False)
        self.client.force_login(self.user)

        patcher = mock.patch('prices.forecast_views._today_kst', return_value=date(2026, 11, 10))
        patcher.start()
        self.addCleanup(patcher.stop)

    def post(self, **body):
        body.setdefault('item_id', self.apple.pk)
        body.setdefault('volume_kg', 100)
        return self.client.post(RECOMMEND_URL, body, content_type='application/json')

    def test_사과_100kg이면_시장_x_시점_8개가_수령액_순(self):
        res = self.post()
        self.assertEqual(res.status_code, 200)
        results = res.json()['data']['results']
        self.assertEqual(len(results), 8)
        nets = [r['net_won'] for r in results]
        self.assertEqual(nets, sorted(nets, reverse=True))
        self.assertEqual([r['rank'] for r in results], list(range(1, 9)))
        # 비용이 전부 0이면 먼 시장 h4(3900원)가 1등: 3900 × 100kg
        self.assertEqual((results[0]['market_id'], results[0]['horizon'], results[0]['net_won']),
                         ('340101', 4, 390000))

    def test_비용_수식_감모율_수수료_운송비_보관비(self):
        res = self.post(loss_rate=10, commission_rate=5, transport_cost_per_km=10, storage_cost_per_week=1000)
        rows = {(r['market_id'], r['horizon']): r for r in res.json()['data']['results']}
        # 먼 시장 h3: 예측 3800, 판매량 90kg → 매출 342000, 수수료 17100, 운송비 111.19km×10=1112, 보관비 2×1000
        r = rows[('340101', 3)]
        self.assertEqual((r['sellable_kg'], r['revenue_won'], r['commission_won']), (90.0, 342000, 17100))
        self.assertEqual((r['transport_won'], r['storage_won']), (1112, 2000))
        self.assertEqual(r['net_won'], 342000 - 17100 - 1112 - 2000)
        self.assertEqual(r['distance_km'], 111.2)
        # 가까운 시장은 운송비 0
        self.assertEqual(rows[('250001', 1)]['transport_won'], 0)

    def test_비용을_바꾸면_다시_계산된다(self):
        a = self.post().json()['data']['results'][0]['net_won']
        b = self.post(storage_cost_per_week=50000).json()['data']['results'][0]
        self.assertNotEqual(a, b['net_won'])
        self.assertEqual(b['horizon'], 1)     # 보관비가 크면 이번 주 판매가 1등

    def test_회원_기본값을_쓰고_요청값이_우선한다(self):
        self.profile.loss_rate = Decimal('20')
        self.profile.storage_cost_per_week = 700
        self.profile.save()
        costs = self.post().json()['meta']['costs']
        self.assertEqual((costs['loss_rate'], costs['storage_cost_per_week']), (20.0, 700))
        costs = self.post(loss_rate=0, storage_cost_per_week=0).json()['meta']['costs']
        self.assertEqual((costs['loss_rate'], costs['storage_cost_per_week']), (0.0, 0))

    def test_위치가_없으면_운송비를_빼고_알린다(self):
        self.profile.lat = self.profile.lng = None
        self.profile.save()
        res = self.post(transport_cost_per_km=10).json()
        self.assertFalse(res['meta']['costs']['transport_applied'])
        self.assertTrue(all(r['transport_won'] == 0 and r['distance_km'] is None for r in res['data']['results']))

    def test_예측구간_하한_상한_수령액(self):
        r = self.post().json()['data']['results'][-1]
        self.assertLessEqual(r['net_low_won'], r['net_won'])
        self.assertLessEqual(r['net_won'], r['net_high_won'])

    def test_휴장일이_있는_시장_시점은_휴장_표시(self):
        MarketClosure.objects.create(market=self.near, closure_date=date(2026, 11, 17))   # h2 주(11/16~22)
        rows = {(r['market_id'], r['horizon']): r for r in self.post().json()['data']['results']}
        self.assertTrue(rows[('250001', 2)]['is_closed'])
        self.assertEqual(rows[('250001', 2)]['closed_dates'], ['2026-11-17'])
        self.assertFalse(rows[('250001', 1)]['is_closed'])
        self.assertFalse(rows[('340101', 2)]['is_closed'])

    def test_희망_시기_표시(self):
        rows = self.post(desired_week='2026-11-18').json()['data']['results']
        self.assertEqual({r['horizon'] for r in rows if r['is_desired']}, {2})

    def test_명절_주의_문구(self):
        Holiday.objects.create(holiday_date=date(2026, 11, 30), name='추석')
        rows = self.post().json()['data']['results']
        self.assertTrue(all(r['holiday_notice'] for r in rows))

    def test_예측_대상_아닌_품목은_시장_비교만(self):
        SettlePrice.objects.create(trade_date=date(2026, 11, 13), market=self.near, item=self.cabbage, grade='ALL',
                                   avg_price=1000, min_price=900, max_price=1100, volume_kg=500)
        res = self.post(item_id=self.cabbage.pk)
        self.assertEqual(res.status_code, 200)
        data = res.json()['data']
        self.assertFalse(data['forecast_available'])
        self.assertEqual(data['results'], [])
        self.assertIn('아직 가격 예측을 제공하지 않습니다', data['message'])
        self.assertEqual(data['market_comparison'][0]['avg_price'], 1000.0)

    def test_지난_주_예측만_남았으면_지난_주는_추천하지_않는다(self):
        with mock.patch('prices.forecast_views._today_kst', return_value=date(2026, 11, 18)):
            horizons = {r['horizon'] for r in self.post().json()['data']['results']}
        self.assertEqual(horizons, {2, 3, 4})       # h1 주(11/9~15)는 이미 지남
        with mock.patch('prices.forecast_views._today_kst', return_value=date(2026, 12, 20)):
            self.assertEqual(self.post().status_code, 503)

    def test_예측이_아직_없으면_503(self):
        Forecast.objects.all().delete()
        res = self.post()
        self.assertEqual((res.status_code, res.json()['error']['code']), (503, 'DATA_NOT_READY'))

    def test_로그인_필요(self):
        res = Client().post(RECOMMEND_URL, {'item_id': 1, 'volume_kg': 1}, content_type='application/json')
        self.assertEqual(res.status_code, 401)
        self.assertEqual(res.json()['error']['code'], 'NOT_AUTHENTICATED')

    def test_CSRF_없으면_403(self):
        c = Client(enforce_csrf_checks=True)
        c.force_login(self.user)
        res = c.post(RECOMMEND_URL, {'item_id': 1, 'volume_kg': 1}, content_type='application/json')
        self.assertEqual((res.status_code, res.json()['error']['code']), (403, 'CSRF_FAILED'))

    def test_입력_오류_400(self):
        for body in ({}, {'item_id': 1}, {'item_id': 1, 'volume_kg': 0}, {'item_id': 1, 'volume_kg': -5},
                     {'item_id': 1, 'volume_kg': 'abc'}, {'item_id': 'x', 'volume_kg': 5},
                     {'item_id': 1, 'volume_kg': 5, 'loss_rate': 101},
                     {'item_id': 1, 'volume_kg': 5, 'transport_cost_per_km': -1},
                     {'item_id': 1, 'volume_kg': 5, 'desired_week': '2026-13-01'}):
            res = self.client.post(RECOMMEND_URL, body, content_type='application/json')
            self.assertEqual((res.status_code, res.json()['error']['code']), (400, 'VALIDATION_ERROR'), body)

    def test_없는_품목_404(self):
        res = self.post(item_id=99999)
        self.assertEqual((res.status_code, res.json()['error']['code']), (404, 'NOT_FOUND'))

    def test_프로필이_없는_계정도_계산된다(self):
        admin = get_user_model().objects.create_user('noprofile', password='pw12345678')
        self.client.force_login(admin)
        res = self.post()
        self.assertEqual(res.status_code, 200)
        self.assertFalse(res.json()['meta']['costs']['transport_applied'])
        costs = res.json()['meta']['costs']
        self.assertEqual((costs['loss_rate'], costs['storage_cost_per_week'], costs['commission_rate']), (0.0, 0, 0.0))

    def test_쿼리_수(self):
        with self.assertNumQueries(8):
            self.post()


# ── 지금 팔면 실수령액 (Y16, REQ-REC-007) ──────────────────────────
SELL_NOW_URL = '/api/recommendations/now'
NOW = date(2026, 11, 16)


def settle(item, market, day, price, volume, lo=None, hi=None, grade='ALL'):
    SettlePrice.objects.create(trade_date=day, market=market, item=item, grade=grade, avg_price=Decimal(price),
                               min_price=Decimal(lo if lo is not None else price),
                               max_price=Decimal(hi if hi is not None else price), volume_kg=Decimal(volume))


class SellNowApiTest(TestCase):
    """POST /api/recommendations/now (REQ-REC-007)."""

    @classmethod
    def setUpTestData(cls):
        # 위도 0 / 경도 1° = 약 111.19km
        cls.near = Market.objects.create(market_id='250001', name='가까운시장', sido='대전', lat=0.001, lng=0.001,
                                         is_collect=True)
        cls.far = Market.objects.create(market_id='340101', name='먼시장', sido='충남', lat=0.001, lng=1.001,
                                        is_collect=True)
        cls.nocoord = Market.objects.create(market_id='110001', name='좌표없음', sido='서울', lat=0, lng=0,
                                            is_collect=True)
        cls.ref = Market.objects.create(market_id='110002', name='참고', sido='서울', lat=1, lng=1,
                                        is_collect=True, is_reference=True)
        cls.apple = Item.objects.create(at_code='0601', name='사과', category='과일', is_forecast=True)
        cls.cabbage = Item.objects.create(at_code='1101', name='배추', category='채소', is_forecast=False)
        for item in (cls.apple, cls.cabbage):
            for m, price in ((cls.near, 3000), (cls.far, 3500), (cls.nocoord, 4000), (cls.ref, 9000)):
                for i in range(10):      # 11/6 ~ 11/15 매일 거래, 하루 1000kg
                    settle(item, m, NOW - timedelta(days=1 + i), price, 1000, lo=price - 200, hi=price + 200)
        cls.user = get_user_model().objects.create_user('farmer', password='pw12345678')
        cls.profile = UserProfile.objects.create(user=cls.user, sido='대전', sigungu='서구', lat=0, lng=0)

    def setUp(self):
        self.client = Client(enforce_csrf_checks=False)
        self.client.force_login(self.user)
        patcher = mock.patch('prices.sell_now._today_kst', return_value=NOW)
        patcher.start()
        self.addCleanup(patcher.stop)

    def post(self, **body):
        body.setdefault('item_id', self.apple.pk)
        body.setdefault('volume_kg', 100)
        return self.client.post(SELL_NOW_URL, body, content_type='application/json')

    def test_수집_대상_시장_전체가_수령액_순이고_참고_시장도_들어간다(self):
        res = self.post()
        self.assertEqual(res.status_code, 200)
        results = res.json()['data']['results']
        self.assertEqual([r['market_id'] for r in results], ['110002', '110001', '340101', '250001'])
        self.assertEqual([r['rank'] for r in results], [1, 2, 3, 4])
        self.assertEqual(results[1]['net_won'], 400000)

    def test_예측_대상이_아닌_품목도_계산된다(self):
        res = self.post(item_id=self.cabbage.pk)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(res.json()['data']['results']), 4)

    def test_7일_밖_거래는_가격에_섞이지_않는다(self):
        SettlePrice.objects.filter(item=self.apple, market=self.near, trade_date=NOW - timedelta(days=9)).update(
            avg_price=1000, volume_kg=99000)
        near = {r['market_id']: r for r in self.post().json()['data']['results']}['250001']
        self.assertEqual(near['price'], 3000.0)

    def test_가중평균_계산(self):
        m = Market.objects.create(market_id='999999', name='새시장', sido='경기', lat=0.5, lng=0.5, is_collect=True)
        settle(self.apple, m, NOW - timedelta(days=1), 1000, 1000)
        settle(self.apple, m, NOW - timedelta(days=2), 2000, 3000)
        row = {r['market_id']: r for r in self.post().json()['data']['results']}['999999']
        self.assertEqual(row['price'], 1750.0)      # (1000×1000 + 2000×3000) / 4000 = 1750
        self.assertEqual((row['recent_min_price'], row['recent_max_price']), (1000.0, 2000.0))

    def test_최저_최고는_하루_평균가_기준(self):
        m = Market.objects.create(market_id='999999', name='새시장', sido='경기', lat=0.5, lng=0.5, is_collect=True)
        settle(self.apple, m, NOW - timedelta(days=1), 2000, 1000, lo=100, hi=9000)
        row = {r['market_id']: r for r in self.post().json()['data']['results']}['999999']
        self.assertEqual((row['recent_min_price'], row['recent_max_price']), (2000.0, 2000.0))

    def test_물량_0인_행은_거래일에_세지_않는다(self):
        m = Market.objects.create(market_id='999999', name='새시장', sido='경기', lat=0.5, lng=0.5, is_collect=True)
        settle(self.apple, m, NOW - timedelta(days=1), 2000, 1000)
        settle(self.apple, m, NOW - timedelta(days=2), 0, 0)
        row = {r['market_id']: r for r in self.post().json()['data']['results']}['999999']
        self.assertEqual((row['trade_days'], row['recent_min_price']), (1, 2000.0))

    def test_예측_대상_아닌_품목은_안내_문구(self):
        meta = self.post(item_id=self.cabbage.pk).json()['meta']
        self.assertFalse(meta['forecast_available'])
        self.assertEqual(meta['message'], '이 품목은 아직 가격 예측을 제공하지 않습니다.')
        meta = self.post().json()['meta']
        self.assertTrue(meta['forecast_available'])
        self.assertNotIn('message', meta)

    def test_쿼리_수(self):
        with self.assertNumQueries(7):
            self.post()

    def test_비용_수식과_운송비(self):
        for days, price in ((3, 3000), (4, 4000)):      # 먼 시장 하루 평균가를 흔들어 최저·최고를 벌린다
            SettlePrice.objects.filter(item=self.apple, market=self.far, trade_date=NOW - timedelta(days=days)
                                       ).update(avg_price=price)
        res = self.post(loss_rate=10, commission_rate=5, transport_cost_per_km=10)
        rows = {r['market_id']: r for r in res.json()['data']['results']}
        r = rows['340101']      # 3500원, 판매량 90kg → 매출 315000, 수수료 15750, 운송비 111.2km×10=1113
        self.assertEqual((r['sellable_kg'], r['revenue_won'], r['commission_won'], r['transport_won']),
                         (90.0, 315000, 15750, 1113))
        self.assertEqual(r['net_won'], 315000 - 15750 - 1113)
        self.assertEqual(r['distance_km'], 111.3)
        self.assertNotIn('storage_won', r)
        self.assertLess(r['net_low_won'], r['net_won'])
        self.assertGreater(r['net_high_won'], r['net_won'])

    def test_좌표_0인_시장은_거리_없음이고_맨_아래로_밀리지_않는다(self):
        res = self.post(transport_cost_per_km=10)
        body = res.json()
        rows = {r['market_id']: r for r in body['data']['results']}
        self.assertIsNone(rows['110001']['distance_km'])
        self.assertEqual(rows['110001']['transport_won'], 0)
        self.assertTrue(any('위치 정보가 없는 시장' in w for w in body['meta']['warnings']))

    def test_내_위치나_운송비_단가가_없으면_운송비_미반영_경고(self):
        res = self.post()      # 단가 0
        meta = res.json()['meta']
        self.assertFalse(meta['costs']['transport_applied'])
        self.assertIn('내 위치 또는 운송비 단가가 없어 운송비를 반영하지 않았습니다.', meta['warnings'])
        self.profile.lat = None
        self.profile.lng = None
        self.profile.save()
        res = self.post(transport_cost_per_km=10)
        self.assertFalse(res.json()['meta']['costs']['transport_applied'])
        self.assertTrue(res.json()['meta']['warnings'])
        # 단가와 위치가 있으면 경고 없음 (좌표 없는 시장 경고만 남을 수 있다)
        self.profile.lat = 0
        self.profile.lng = 0
        self.profile.save()
        meta = self.post(transport_cost_per_km=10).json()['meta']
        self.assertTrue(meta['costs']['transport_applied'])
        self.assertNotIn('내 위치 또는 운송비 단가가 없어 운송비를 반영하지 않았습니다.', meta['warnings'])

    def test_거래가_적은_시장과_물량_경고(self):
        m = Market.objects.create(market_id='999999', name='한산한시장', sido='경기', lat=0.5, lng=0.5, is_collect=True)
        settle(self.apple, m, NOW - timedelta(days=1), 5000, 300)
        rows = {r['market_id']: r for r in self.post(volume_kg=5000).json()['data']['results']}
        self.assertTrue(rows['999999']['low_trade'])
        self.assertEqual((rows['999999']['trade_days'], rows['999999']['recent_volume_kg']), (1, 300.0))
        self.assertFalse(rows['250001']['low_trade'])
        # 5000kg는 가까운 시장 일평균 1000kg보다 많다 → 물량 경고. 100kg은 아니다
        self.assertTrue(rows['250001']['volume_warning'])
        rows = {r['market_id']: r for r in self.post(volume_kg=100).json()['data']['results']}
        self.assertFalse(rows['250001']['volume_warning'])

    def test_기준일이_오래되면_표시(self):
        meta = self.post().json()['meta']
        self.assertEqual(meta['base_date'], '2026-11-15')
        self.assertFalse(meta['is_stale'])
        with mock.patch('prices.sell_now._today_kst', return_value=NOW + timedelta(days=10)):
            body = self.post().json()
        self.assertTrue(body['meta']['is_stale'])
        self.assertTrue(any('오래되어' in w for w in body['meta']['warnings']))

    def test_최근_7일_거래_없는_시장은_빠진다(self):
        m = Market.objects.create(market_id='999999', name='옛시장', sido='경기', lat=0.5, lng=0.5, is_collect=True)
        settle(self.apple, m, NOW - timedelta(days=12), 5000, 1000)
        ids = [r['market_id'] for r in self.post().json()['data']['results']]
        self.assertNotIn('999999', ids)

    def test_정산_데이터가_없으면_빈_결과(self):
        other = Item.objects.create(at_code='9999', name='없는품목', category='기타', is_forecast=False)
        res = self.post(item_id=other.pk)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()['data']['results'], [])
        self.assertIsNone(res.json()['meta']['base_date'])

    def test_등급을_고르면_그_등급만_쓴다(self):
        settle(self.apple, self.near, NOW - timedelta(days=1), 8000, 500, grade='특')
        res = self.post(grade='특')
        self.assertEqual([r['market_id'] for r in res.json()['data']['results']], ['250001'])
        self.assertEqual(res.json()['data']['results'][0]['price'], 8000.0)

    def test_로그인_필요(self):
        res = Client().post(SELL_NOW_URL, {'item_id': 1, 'volume_kg': 1}, content_type='application/json')
        self.assertEqual((res.status_code, res.json()['error']['code']), (401, 'NOT_AUTHENTICATED'))

    def test_CSRF_없으면_403(self):
        c = Client(enforce_csrf_checks=True)
        c.force_login(self.user)
        res = c.post(SELL_NOW_URL, {'item_id': 1, 'volume_kg': 1}, content_type='application/json')
        self.assertEqual((res.status_code, res.json()['error']['code']), (403, 'CSRF_FAILED'))

    def test_입력_오류_400과_없는_품목_404(self):
        for body in ({}, {'item_id': 1}, {'item_id': 1, 'volume_kg': 0}, {'item_id': 'x', 'volume_kg': 5},
                     {'item_id': 1, 'volume_kg': 5, 'loss_rate': 101}, {'item_id': 1, 'volume_kg': 'abc'},
                     {'item_id': 1, 'volume_kg': 0.09}, {'item_id': 1, 'volume_kg': 5, 'commission_rate': -1},
                     {'item_id': 1, 'volume_kg': 5, 'transport_cost_per_km': -1}, []):
            res = self.client.post(SELL_NOW_URL, body, content_type='application/json')
            self.assertEqual((res.status_code, res.json()['error']['code']), (400, 'VALIDATION_ERROR'), body)
        res = self.post(item_id=99999)
        self.assertEqual((res.status_code, res.json()['error']['code']), (404, 'NOT_FOUND'))

    def test_프로필이_없는_계정도_계산된다(self):
        user = get_user_model().objects.create_user('noprofile', password='pw12345678')
        self.client.force_login(user)
        res = self.post()
        self.assertEqual(res.status_code, 200)
        self.assertFalse(res.json()['meta']['costs']['transport_applied'])
