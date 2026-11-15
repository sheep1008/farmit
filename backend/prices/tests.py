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
        self.put(self.ref, self.apple, date(2026, 10, 30), 4000)          # 참고 시장은 제외
        both = Market.objects.create(market_id='999001', name='수집겸참고', sido='서울', lat=0, lng=0,
                                     is_collect=True, is_reference=True)     # 두 표시가 다 있어도 참고 시장이면 제외
        self.put(both, self.apple, date(2026, 10, 30), 4100)
        res = self.get(date='2026-10-30')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()['data'], [
            {'market_id': '250001', 'market_name': '대전오정', 'avg_price': 3507.0, 'volume_kg': 2310.0},
            {'market_id': '250003', 'market_name': '대전노은', 'avg_price': 3763.0, 'volume_kg': 1820.0},
            {'market_id': '340101', 'market_name': '천안', 'avg_price': None, 'volume_kg': 0},
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
