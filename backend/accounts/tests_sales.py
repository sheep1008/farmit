"""판매 기록 API (Y07: REQ-SAL-001, REQ-SAL-002). 테스트 러너가 찾도록 tests 패키지가 아니라 같은 이름 규칙의 파일."""
from datetime import date
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import Client, TestCase

from codes.models import Item, Market
from prices.models import SettlePrice

from .models import SaleRecord, UserProfile

URL = '/api/sales'
TODAY = date(2026, 11, 15)


class SalesApiTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.user = User.objects.create_user('farmer', password='pw12345678')
        cls.other = User.objects.create_user('other', password='pw12345678')
        for u in (cls.user, cls.other):
            UserProfile.objects.create(user=u, sido='대전', sigungu='서구')
        cls.m1 = Market.objects.create(market_id='250001', name='대전오정', sido='대전', lat=0, lng=0, is_collect=True)
        cls.m2 = Market.objects.create(market_id='340101', name='천안', sido='충남', lat=0, lng=0, is_collect=True)
        cls.apple = Item.objects.create(at_code='0601', name='사과', category='과일')
        SettlePrice.objects.create(trade_date=date(2026, 11, 10), market=cls.m1, item=cls.apple, grade='ALL',
                                   avg_price=3000, min_price=2000, max_price=4000, volume_kg=1000)

    def setUp(self):
        self.client = Client()
        self.client.force_login(self.user)
        patcher = mock.patch('accounts.sales_views._today_kst', return_value=TODAY)
        patcher.start()
        self.addCleanup(patcher.stop)

    def body(self, **kw):
        base = {'sale_date': '2026-11-10', 'market_id': '250001', 'item_id': self.apple.pk,
                'volume_kg': 100, 'amount_won': 330000}
        base.update(kw)
        return base

    def post(self, **kw):
        return self.client.post(URL, self.body(**kw), content_type='application/json')

    def make(self, user=None, **kw):
        fields = dict(user=user or self.user, sale_date=date(2026, 11, 10), market=self.m1, item=self.apple,
                      grade='ALL', volume_kg=100, amount_won=330000)
        fields.update(kw)
        return SaleRecord.objects.create(**fields)

    # --- REQ-SAL-001 ---
    def test_저장하면_201과_목록에_나타난다(self):
        res = self.post()
        self.assertEqual(res.status_code, 201)
        data = res.json()['data']
        self.assertEqual((data['market_name'], data['item_name'], data['unit_price']), ('대전오정', '사과', 3300.0))
        listed = self.client.get(URL).json()
        self.assertEqual([r['id'] for r in listed['data']], [data['id']])

    def test_수정이_반영된다(self):
        rec = self.make()
        res = self.client.patch(f'{URL}/{rec.pk}', {'amount_won': 300000, 'volume_kg': 50},
                                content_type='application/json')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()['data']['unit_price'], 6000.0)
        rec.refresh_from_db()
        self.assertEqual(rec.amount_won, 300000)

    def test_수정으로_시장_품목을_바꿀_수_있다(self):
        rec = self.make()
        res = self.client.patch(f'{URL}/{rec.pk}', {'market_id': '340101'}, content_type='application/json')
        self.assertEqual(res.json()['data']['market_name'], '천안')
        self.assertIsNone(res.json()['data']['avg_price'])

    def test_삭제가_반영된다(self):
        rec = self.make()
        self.assertEqual(self.client.delete(f'{URL}/{rec.pk}').status_code, 204)
        self.assertFalse(SaleRecord.objects.filter(pk=rec.pk).exists())
        self.assertEqual(self.client.get(URL).json()['data'], [])

    def test_남의_기록은_404(self):
        rec = self.make(user=self.other)
        for call in (lambda: self.client.patch(f'{URL}/{rec.pk}', {'amount_won': 1}, content_type='application/json'),
                     lambda: self.client.delete(f'{URL}/{rec.pk}')):
            res = call()
            self.assertEqual((res.status_code, res.json()['error']['code'] if res.content else None),
                             (404, 'NOT_FOUND'))
        self.assertTrue(SaleRecord.objects.filter(pk=rec.pk).exists())
        self.assertEqual(self.client.get(URL).json()['data'], [])

    def test_없는_기록과_아주_큰_번호는_404(self):
        self.assertEqual(self.client.delete(f'{URL}/999999').status_code, 404)
        self.assertEqual(self.client.delete(f'{URL}/{10 ** 30}').status_code, 404)

    def test_입력_오류_400(self):
        cases = [dict(volume_kg=0), dict(volume_kg='abc'), dict(amount_won=-1), dict(amount_won=1.5),
                 dict(sale_date='2026-11-16'), dict(sale_date='2026-13-01'), dict(market_id='zzzzzz'),
                 dict(item_id=99999), dict(item_id='x'), dict(grade='x' * 11), dict(amount_won=10 ** 14)]
        for kw in cases:
            res = self.post(**kw)
            self.assertEqual((res.status_code, res.json()['error']['code']), (400, 'VALIDATION_ERROR'), kw)
        for field in ('sale_date', 'market_id', 'item_id', 'volume_kg', 'amount_won'):
            data = self.body()
            del data[field]
            res = self.client.post(URL, data, content_type='application/json')
            self.assertEqual(res.status_code, 400, field)

    def test_수정_입력_오류도_400(self):
        rec = self.make()
        res = self.client.patch(f'{URL}/{rec.pk}', {'volume_kg': 0}, content_type='application/json')
        self.assertEqual(res.status_code, 400)

    def test_등급을_안_주면_ALL(self):
        self.assertEqual(self.post().json()['data']['grade'], 'ALL')

    def test_로그인_필요와_CSRF(self):
        self.assertEqual(Client().get(URL).status_code, 401)
        c = Client(enforce_csrf_checks=True)
        c.force_login(self.user)
        res = c.post(URL, self.body(), content_type='application/json')
        self.assertEqual((res.status_code, res.json()['error']['code']), (403, 'CSRF_FAILED'))

    def test_목록은_내_것만_최신순_합계와_페이지(self):
        a = self.make(sale_date=date(2026, 11, 1), volume_kg=10, amount_won=100)
        b = self.make(sale_date=date(2026, 11, 9), volume_kg=20, amount_won=200)
        self.make(user=self.other, amount_won=999999)
        res = self.client.get(URL).json()
        self.assertEqual([r['id'] for r in res['data']], [b.pk, a.pk])
        self.assertEqual((res['meta']['total'], res['meta']['total_volume_kg'], res['meta']['total_amount_won']),
                         (2, 30.0, 300))
        page2 = self.client.get(URL, {'size': 1, 'page': 2}).json()
        self.assertEqual([r['id'] for r in page2['data']], [a.pk])
        self.assertEqual(page2['meta']['total_amount_won'], 300)     # 합계는 페이지가 아니라 기간 전체
        self.assertEqual(self.client.get(URL, {'page': 9}).json()['data'], [])

    def test_기간_필터(self):
        self.make(sale_date=date(2026, 11, 1))
        b = self.make(sale_date=date(2026, 11, 9))
        res = self.client.get(URL, {'from': '2026-11-05', 'to': '2026-11-09'}).json()
        self.assertEqual([r['id'] for r in res['data']], [b.pk])
        self.assertEqual(self.client.get(URL, {'from': '2026-11-09', 'to': '2026-11-01'}).status_code, 400)
        self.assertEqual(self.client.get(URL, {'from': 'x'}).status_code, 400)
        self.assertEqual(self.client.get(URL, {'size': 101}).status_code, 400)

    # --- REQ-SAL-002 ---
    def test_기록마다_평균_대비_퍼센트(self):
        # 단가 3300 / 평균 3000 → +10.0%
        self.assertEqual(self.post().json()['data']['vs_avg_pct'], 10.0)
        self.assertEqual(self.post().json()['data']['avg_price'], 3000.0)
        rec = self.make(amount_won=270000)      # 2700 → -10.0%
        rows = {r['id']: r for r in self.client.get(URL).json()['data']}
        self.assertEqual(rows[rec.pk]['vs_avg_pct'], -10.0)

    def test_같은_날_시장_품목_등급이_다르면_비교하지_않는다(self):
        self.assertIsNone(self.post(sale_date='2026-11-11').json()['data']['vs_avg_pct'])
        self.assertIsNone(self.post(market_id='340101').json()['data']['vs_avg_pct'])
        self.assertIsNone(self.post(grade='특').json()['data']['vs_avg_pct'])

    def test_등급을_주면_그_등급_평균과_비교(self):
        SettlePrice.objects.create(trade_date=date(2026, 11, 10), market=self.m1, item=self.apple, grade='특',
                                   avg_price=4000, min_price=3000, max_price=5000, volume_kg=100)
        self.assertEqual(self.post(grade='특', amount_won=360000).json()['data']['vs_avg_pct'], -10.0)

    def test_목록_쿼리_수는_기록_수와_무관(self):
        for _ in range(5):
            self.make()
        with self.assertNumQueries(5):    # 세션·회원 2 + 개수·합계 + 목록 + 정산 평균
            self.client.get(URL)

    def test_나중에_정산이_들어오면_값이_채워진다(self):
        rec = self.make(sale_date=date(2026, 11, 12))
        self.assertIsNone(self.client.get(URL).json()['data'][0]['vs_avg_pct'])
        SettlePrice.objects.create(trade_date=date(2026, 11, 12), market=self.m1, item=self.apple, grade='ALL',
                                   avg_price=3300, min_price=1, max_price=9, volume_kg=10)
        self.assertEqual(self.client.get(URL).json()['data'][0]['vs_avg_pct'], 0.0)
        # 수정으로 단가가 바뀌면 평균 대비도 다시 계산된다
        res = self.client.patch(f'{URL}/{rec.pk}', {'amount_won': 363000}, content_type='application/json')
        self.assertEqual(res.json()['data']['vs_avg_pct'], 10.0)

    def test_비로그인은_모든_메서드가_401(self):
        rec = self.make()
        anon = Client()
        for res in (anon.get(URL), anon.post(URL, self.body(), content_type='application/json'),
                    anon.patch(f'{URL}/{rec.pk}', {}, content_type='application/json'), anon.delete(f'{URL}/{rec.pk}')):
            self.assertEqual((res.status_code, res.json()['error']['code']), (401, 'NOT_AUTHENTICATED'))

    def test_PATCH_DELETE도_CSRF가_필요하다(self):
        rec = self.make()
        c = Client(enforce_csrf_checks=True)
        c.force_login(self.user)
        for res in (c.patch(f'{URL}/{rec.pk}', {'amount_won': 1}, content_type='application/json'),
                    c.delete(f'{URL}/{rec.pk}')):
            self.assertEqual((res.status_code, res.json()['error']['code']), (403, 'CSRF_FAILED'))

    def test_기록이_없으면_200_빈_배열과_합계_0(self):
        res = self.client.get(URL).json()
        self.assertEqual(res['data'], [])
        self.assertEqual((res['meta']['total'], res['meta']['total_volume_kg'], res['meta']['total_amount_won']),
                         (0, 0.0, 0))

    def test_남의_기록은_잘못된_본문이어도_404가_먼저(self):
        rec = self.make(user=self.other)
        res = self.client.patch(f'{URL}/{rec.pk}', {'volume_kg': 0}, content_type='application/json')
        self.assertEqual(res.status_code, 404)

    def test_오늘은_되고_내일은_400이며_오류_코드(self):
        self.assertEqual(self.post(sale_date='2026-11-15').status_code, 201)
        self.assertEqual(self.post(sale_date='1999-12-31').status_code, 400)
        res = self.post(sale_date='2026-11-16')
        self.assertIn('sale_date', res.json()['error']['details'])
        rec = self.make()
        res = self.client.patch(f'{URL}/{rec.pk}', {'volume_kg': 0}, content_type='application/json')
        self.assertEqual((res.status_code, res.json()['error']['code']), (400, 'VALIDATION_ERROR'))
        self.assertIn('volume_kg', res.json()['error']['details'])
        self.assertEqual(self.client.get(URL, {'from': 'x'}).json()['error']['code'], 'VALIDATION_ERROR')
        self.assertEqual(self.client.get(URL, {'size': 101}).json()['error']['code'], 'INVALID_PARAMETER')

    # --- 탈퇴 ---
    def test_회원_탈퇴하면_판매_기록도_삭제된다(self):
        self.make()
        self.user.delete()
        self.assertFalse(SaleRecord.objects.filter(user_id=self.user.pk).exists())
