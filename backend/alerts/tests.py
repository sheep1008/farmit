from django.contrib.auth import get_user_model
from django.test import TestCase

from accounts.models import UserInterestItem
from codes.models import Item, ItemProducingArea, WeatherStation

from .models import Alert, SpecialEvent
from .warning_events import handle_warning_event


def warning_msg(region_code, region_name, status='발표', **kw):
    """Flink가 weather.warning.event로 보내는 메시지 모양"""
    msg = {
        'source_key': f'202611061100_{region_code}_3_0',
        'announced_at': '2026-11-06T02:00:00',
        'region_code': region_code,
        'region_name': region_name,
        'warning_type': '한파',
        'level': '주의보',
        'status': status,
        'effective_at': '2026-11-06T12:00:00',
        'ended_at': None,
    }
    msg.update(kw)
    return msg


class WarningAlertTests(TestCase):
    """warning_zone은 마이그레이션 0007이 테스트 DB에도 넣어 둔다"""

    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        station = WeatherStation.objects.create(station_id=1, name='테스트', sido='경기도', lat=0, lng=0)
        cls.apple = Item.objects.create(at_code='0601', name='사과', category='과일')
        cls.pear = Item.objects.create(at_code='0602', name='배', category='과일')
        # 사과 주산지: 경기 가평군, 강원 평창군(옛 시도 표기), 서울 강남구 / 배 주산지: 충남 천안시
        for item, sido, sigungu in [
            (cls.apple, '경기도', '가평군'), (cls.apple, '강원도', '평창군'),
            (cls.apple, '서울특별시', '강남구'), (cls.pear, '충청남도', '천안시'),
        ]:
            ItemProducingArea.objects.create(item=item, sido=sido, sigungu=sigungu, station=station, volume_share=10)
        cls.apple_user = User.objects.create_user('apple')
        cls.pear_user = User.objects.create_user('pear')
        UserInterestItem.objects.create(user=cls.apple_user, item=cls.apple)
        UserInterestItem.objects.create(user=cls.pear_user, item=cls.pear)

    def alerted_users(self):
        return set(Alert.objects.values_list('user__username', flat=True))

    def test_주산지_구역_특보는_그_품목_회원에게만_알림(self):
        result, users = handle_warning_event(warning_msg('L1011400', '가평군'))
        self.assertEqual(users, 1)
        self.assertEqual(self.alerted_users(), {'apple'})
        event = SpecialEvent.objects.get()
        self.assertEqual((event.sido, event.sigungu), ('경기도', '가평군'))
        self.assertEqual(event.title, '가평군 한파주의보 발표')
        self.assertEqual(event.detail['effective_at'], '2026-11-06T12:00:00')
        self.assertEqual(event.occurred_at.isoformat(), '2026-11-06T02:00:00+00:00')

    def test_같은_메시지를_두_번_받아도_알림은_한_번(self):
        msg = warning_msg('L1011400', '가평군')
        handle_warning_event(msg)
        handle_warning_event(msg)
        self.assertEqual(SpecialEvent.objects.count(), 1)
        self.assertEqual(Alert.objects.count(), 1)

    def test_하위_구역과_옛_시도_표기도_찾는다(self):
        # 평창군평지(L1022410) → 강원특별자치도 평창군. 주산지는 '강원도'로 저장되어 있다
        handle_warning_event(warning_msg('L1022410', '평창군평지'))
        self.assertEqual(self.alerted_users(), {'apple'})

    def test_광역시_권역은_시도_전체로_본다(self):
        # 서울동남권(L1100100) → 서울특별시 전체 → 강남구 주산지 포함
        handle_warning_event(warning_msg('L1100100', '서울동남권'))
        self.assertEqual(self.alerted_users(), {'apple'})

    def test_해제는_알림을_만들지_않는다(self):
        result, users = handle_warning_event(warning_msg('L1011400', '가평군', status='해제'))
        self.assertTrue(result.startswith('건너뜀'))
        self.assertFalse(SpecialEvent.objects.exists())

    def test_해상_구역과_모르는_구역은_건너뛴다(self):
        handle_warning_event(warning_msg('S1151100', '강원북부앞바다'))
        handle_warning_event(warning_msg('L9999999', '없는구역'))
        self.assertFalse(SpecialEvent.objects.exists())

    def test_관심_회원이_없어도_특수_상황은_남긴다(self):
        result, users = handle_warning_event(warning_msg('L1031200', '당진시'))
        self.assertEqual(users, 0)
        self.assertEqual(SpecialEvent.objects.count(), 1)


class AlertApiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        from datetime import datetime, timezone as tz
        User = get_user_model()
        cls.me = User.objects.create_user('me00')
        cls.other = User.objects.create_user('other')

        def event(ref, wtype, hour):
            return SpecialEvent.objects.create(
                event_type='WARNING', sido='경기도', sigungu='가평군',
                occurred_at=datetime(2026, 11, 6, hour, tzinfo=tz.utc),
                title=f'가평군 {wtype}주의보 발표', detail={'warning_type': wtype},
                source_url='https://www.weather.go.kr', source_ref=ref)

        cls.cold = event('a', '한파', 2)
        cls.rain = event('b', '호우', 3)
        cls.weird = event('c', '없는유형', 4)
        cls.mine_cold = Alert.objects.create(user=cls.me, special_event=cls.cold)
        cls.mine_rain = Alert.objects.create(user=cls.me, special_event=cls.rain)
        cls.others = Alert.objects.create(user=cls.other, special_event=cls.cold)

    def login(self):
        self.client.force_login(self.me)

    def test_로그인_없으면_401(self):
        for method, url in [('get', '/api/alerts'), ('get', f'/api/alerts/{self.mine_cold.id}'),
                            ('patch', f'/api/alerts/{self.mine_cold.id}/read')]:
            res = getattr(self.client, method)(url)
            self.assertEqual((res.status_code, res.json()['error']['code']), (401, 'NOT_AUTHENTICATED'))

    def test_목록은_내_알림만_최신순(self):
        self.login()
        res = self.client.get('/api/alerts')
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual([a['id'] for a in body['data']], [self.mine_rain.id, self.mine_cold.id])
        self.assertEqual(body['meta'], {'page': 1, 'size': 20, 'total': 2})
        self.assertFalse(body['data'][0]['is_read'])

    def test_페이지_나눔(self):
        self.login()
        body = self.client.get('/api/alerts?page=2&size=1').json()
        self.assertEqual([a['id'] for a in body['data']], [self.mine_cold.id])
        self.assertEqual(body['meta']['total'], 2)

    def test_잘못된_쿼리는_400(self):
        self.login()
        for q in ['size=500', 'page=0', 'page=abc', 'unread=maybe']:
            res = self.client.get(f'/api/alerts?{q}')
            self.assertEqual((res.status_code, res.json()['error']['code']), (400, 'INVALID_PARAMETER'), q)

    def test_unread_필터(self):
        self.login()
        self.client.patch(f'/api/alerts/{self.mine_rain.id}/read')
        body = self.client.get('/api/alerts?unread=true').json()
        self.assertEqual([a['id'] for a in body['data']], [self.mine_cold.id])
        self.assertEqual(body['meta']['total'], 1)

    def test_남의_알림은_404(self):
        self.login()
        for method, url in [('get', f'/api/alerts/{self.others.id}'), ('patch', f'/api/alerts/{self.others.id}/read'),
                            ('get', '/api/alerts/999999')]:
            res = getattr(self.client, method)(url)
            self.assertEqual((res.status_code, res.json()['error']['code']), (404, 'NOT_FOUND'))
        self.others.refresh_from_db()
        self.assertIsNone(self.others.read_at)

    def test_읽음_처리하면_read_at이_채워지고_다시_해도_유지(self):
        self.login()
        res = self.client.patch(f'/api/alerts/{self.mine_cold.id}/read')
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json()['data']['is_read'])
        self.mine_cold.refresh_from_db()
        first = self.mine_cold.read_at
        self.assertIsNotNone(first)
        self.client.patch(f'/api/alerts/{self.mine_cold.id}/read')
        self.mine_cold.refresh_from_db()
        self.assertEqual(self.mine_cold.read_at, first)

    def test_상세에_체크리스트와_출처가_있다(self):
        self.login()
        data = self.client.get(f'/api/alerts/{self.mine_cold.id}').json()['data']
        self.assertEqual(data['title'], '가평군 한파주의보 발표')
        self.assertEqual(data['source_url'], 'https://www.weather.go.kr')
        cl = data['checklist']
        self.assertTrue(cl['before'] and cl['after'] and cl['sources'])
        self.assertTrue(all(s['name'] for s in cl['sources']))
        # 상세를 열기만 해서는 읽음 처리되지 않는다
        self.mine_cold.refresh_from_db()
        self.assertIsNone(self.mine_cold.read_at)

    def test_유형별로_다른_체크리스트_모르는_유형은_일반(self):
        from .checklists import GENERIC
        self.login()
        rain = self.client.get(f'/api/alerts/{self.mine_rain.id}').json()['data']['checklist']
        cold = self.client.get(f'/api/alerts/{self.mine_cold.id}').json()['data']['checklist']
        self.assertNotEqual(rain['before'], cold['before'])
        alert = Alert.objects.create(user=self.me, special_event=self.weird)
        generic = self.client.get(f'/api/alerts/{alert.id}').json()['data']['checklist']
        self.assertEqual(generic['before'], GENERIC['before'])
