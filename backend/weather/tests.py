from datetime import datetime
from unittest import mock

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from accounts.models import UserProfile
from weather import current

URL = '/api/weather/current'
NOW = datetime(2026, 11, 20, 11, 20, tzinfo=current.KST)
NCST = [{'category': c, 'obsrValue': v} for c, v in
        (('PTY', '0'), ('REH', '68'), ('RN1', '0'), ('T1H', '3.4'), ('WSD', '2.4'))]
FCST = [{'category': 'SKY', 'fcstDate': '20261120', 'fcstTime': '1300', 'fcstValue': '4'},
        {'category': 'SKY', 'fcstDate': '20261120', 'fcstTime': '1200', 'fcstValue': '1'},
        {'category': 'PTY', 'fcstDate': '20261120', 'fcstTime': '1200', 'fcstValue': '0'}]


def fake_call(ncst=NCST, fcst=FCST):
    return lambda service, base, nx, ny: ncst if service == 'getUltraSrtNcst' else fcst


class GridTests(TestCase):
    def test_known_points(self):
        """기상청 격자표의 값과 같다 (서울 중구 60·127, 부산 중구 97·74)"""
        self.assertEqual(current.to_grid(37.5636, 126.9976), (60, 127))
        self.assertEqual(current.to_grid(35.1064, 129.0324), (97, 74))


@override_settings(DATA_GO_KR_KEY='test-key')
class CurrentWeatherTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_observation_with_nearest_forecast_sky(self):
        with mock.patch('weather.current._call', side_effect=fake_call()) as call:
            data = current.current_weather(36.8, 127.1, NOW)
        self.assertEqual((data['summary'], data['sky'], data['precip_type']), ('맑음', '맑음', None))
        self.assertEqual((data['temp_c'], data['humidity_pct'], data['wind_ms']), (3.4, 68.0, 2.4))
        self.assertEqual(data['observed_at'], '2026-11-20T11:00:00+09:00')
        # 실황은 15분 전의 정각, 예보는 45분 전의 30분 발표분을 묻는다
        self.assertEqual([c.args[1].strftime('%H%M') for c in call.call_args_list], ['1100', '1030'])

    def test_precipitation_wins_over_sky(self):
        snow = [{'category': 'PTY', 'obsrValue': '3'}, {'category': 'T1H', 'obsrValue': '-1.0'}]
        with mock.patch('weather.current._call', side_effect=fake_call(ncst=snow)):
            data = current.current_weather(36.8, 127.1, NOW)
        self.assertEqual((data['summary'], data['precip_type'], data['temp_c']), ('눈', '눈', -1.0))

    def test_forecast_failure_only_drops_sky(self):
        with mock.patch('weather.current._call', side_effect=fake_call(fcst=None)):
            data = current.current_weather(36.8, 127.1, NOW)
        self.assertIsNone(data['sky'])
        self.assertEqual(data['temp_c'], 3.4)

    def test_same_grid_is_cached_and_failure_is_not_retried_at_once(self):
        with mock.patch('weather.current._call', side_effect=fake_call()) as call:
            current.current_weather(36.8, 127.1, NOW)
            current.current_weather(36.8, 127.1, NOW)
        self.assertEqual(call.call_count, 2)  # 실황 1 + 예보 1, 두 번째 요청은 캐시
        cache.clear()
        with mock.patch('weather.current._call', return_value=None) as call:
            self.assertIsNone(current.current_weather(36.8, 127.1, NOW))
            self.assertIsNone(current.current_weather(36.8, 127.1, NOW))
        self.assertEqual(call.call_count, 1)


class CurrentWeatherApiTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.user = User.objects.create_user('farmer', password='pw12345678!')
        UserProfile.objects.create(user=self.user, sido='충남', sigungu='천안시', lat=36.815, lng=127.114)

    def test_requires_login(self):
        self.assertEqual(self.client.get(URL).status_code, 401)

    def test_returns_my_location_weather(self):
        self.client.force_login(self.user)
        with override_settings(DATA_GO_KR_KEY='test-key'), \
                mock.patch('weather.current._call', side_effect=fake_call()):
            res = self.client.get(URL)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()['data']['location'], '충남 천안시')
        self.assertEqual(res.json()['data']['summary'], '맑음')

    def test_unavailable_without_key_or_on_upstream_failure(self):
        self.client.force_login(self.user)
        res = self.client.get(URL)  # 테스트 설정은 키가 없다
        self.assertEqual((res.status_code, res.json()['error']['code']), (503, 'DATA_NOT_READY'))

    def test_unknown_location_is_404(self):
        UserProfile.objects.filter(user=self.user).update(sido='없는도', sigungu='없는시', lat=None, lng=None)
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(URL).status_code, 404)
