from django.contrib.auth import get_user_model
from django.core.cache import cache
from rest_framework.test import APIClient, APITestCase

from codes.models import Item

from .models import UserInterestItem, UserProfile

User = get_user_model()

SIGNUP_URL = '/api/auth/signup'
LOGIN_URL = '/api/auth/login'
LOGOUT_URL = '/api/auth/logout'
ME_URL = '/api/users/me'


class AccountTestBase(APITestCase):
    def setUp(self):
        # 로그인 실패 횟수가 캐시(메모리)에 남아 다른 테스트에 영향을 주지 않게 비운다
        cache.clear()
        self.apple = Item.objects.create(at_code='T001', name='사과', category='과일')
        self.pear = Item.objects.create(at_code='T002', name='배', category='과일')

    def signup_payload(self, **override):
        payload = {
            'username': 'farmer01',
            'password': 'apple2026',
            'password_confirm': 'apple2026',
            'sido': '충청북도',
            'sigungu': '충주시',
            'interest_item_ids': [self.apple.item_id, self.pear.item_id],
            'agree_terms': True,
            'agree_privacy': True,
        }
        payload.update(override)
        return payload

    def signup(self, **override):
        return self.client.post(SIGNUP_URL, self.signup_payload(**override), format='json')


class SignupTests(AccountTestBase):
    """REQ-USR-001: 중복 아이디로 가입하면 오류 안내가 표시된다."""

    def test_signup_creates_three_tables_and_logs_in(self):
        res = self.signup()
        self.assertEqual(res.status_code, 201)
        self.assertEqual(res.data['data']['username'], 'farmer01')
        self.assertEqual([i['name'] for i in res.data['data']['interest_items']], ['사과', '배'])
        self.assertTrue(UserProfile.objects.filter(user__username='farmer01').exists())
        self.assertEqual(UserInterestItem.objects.count(), 2)
        # 가입과 동시에 로그인 처리되었는지
        self.assertEqual(self.client.get(ME_URL).status_code, 200)

    def test_password_is_stored_as_hash(self):
        self.signup()
        self.assertNotEqual(User.objects.get(username='farmer01').password, 'apple2026')

    def test_duplicate_username_returns_409(self):
        self.signup()
        res = self.signup()
        self.assertEqual(res.status_code, 409)
        self.assertEqual(res.data['error']['code'], 'DUPLICATE_USERNAME')

    def test_rule_violations_return_400_with_details(self):
        res = self.signup(username='AB', password='abc', password_confirm='abc')
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.data['error']['code'], 'VALIDATION_ERROR')
        self.assertIn('username', res.data['error']['details'])
        self.assertIn('password', res.data['error']['details'])

    def test_password_mismatch_and_missing_agreement(self):
        res = self.signup(password_confirm='apple9999', agree_terms=False)
        self.assertEqual(res.status_code, 400)
        details = res.data['error']['details']
        self.assertIn('password_confirm', details)
        self.assertIn('agree_terms', details)
        self.assertNotIn('agree_privacy', details)

    def test_unknown_item_id_returns_400(self):
        res = self.signup(interest_item_ids=[self.apple.item_id, 99999])
        self.assertEqual(res.status_code, 400)
        self.assertIn('interest_item_ids', res.data['error']['details'])
        self.assertFalse(User.objects.exists())

    def test_more_than_five_items_returns_400(self):
        res = self.signup(interest_item_ids=[1, 2, 3, 4, 5, 6])
        self.assertEqual(res.status_code, 400)

    def test_check_username(self):
        url = '/api/auth/check-username'
        self.assertTrue(self.client.get(url, {'username': 'farmer01'}).data['data']['available'])
        self.signup()
        self.assertFalse(self.client.get(url, {'username': 'farmer01'}).data['data']['available'])
        self.assertEqual(self.client.get(url, {'username': 'AB!'}).status_code, 400)
        self.assertEqual(self.client.get(url, {'username': ''}).status_code, 400)


class LoginTests(AccountTestBase):
    """REQ-USR-002: 로그인하면 회원 메뉴가 보이고, 로그아웃하면 사라진다."""

    def setUp(self):
        super().setUp()
        self.signup()
        self.client.post(LOGOUT_URL)

    def login(self, password='apple2026'):
        return self.client.post(LOGIN_URL, {'username': 'farmer01', 'password': password}, format='json')

    def test_login_then_logout(self):
        self.assertEqual(self.client.get(ME_URL).status_code, 401)
        res = self.login()
        self.assertEqual(res.status_code, 200)
        self.assertIn('chat_remaining_today', res.data['data'])  # 로그인 응답은 me와 같은 모양
        self.assertEqual(self.client.get(ME_URL).status_code, 200)
        self.assertEqual(self.client.post(LOGOUT_URL).status_code, 204)
        self.assertEqual(self.client.get(ME_URL).status_code, 401)

    def test_logout_when_not_logged_in_is_204(self):
        self.assertEqual(self.client.post(LOGOUT_URL).status_code, 204)

    def test_wrong_password_returns_401(self):
        res = self.login('wrong1234')
        self.assertEqual(res.status_code, 401)
        self.assertEqual(res.data['error']['code'], 'INVALID_CREDENTIALS')

    def test_unknown_username_gives_same_error(self):
        res = self.client.post(LOGIN_URL, {'username': 'nobody1', 'password': 'apple2026'}, format='json')
        self.assertEqual(res.status_code, 401)
        self.assertEqual(res.data['error']['code'], 'INVALID_CREDENTIALS')

    def test_five_failures_lock_even_correct_password(self):
        for _ in range(5):
            self.assertEqual(self.login('wrong1234').status_code, 401)
        res = self.login('apple2026')
        self.assertEqual(res.status_code, 429)
        self.assertEqual(res.data['error']['code'], 'TOO_MANY_LOGIN_ATTEMPTS')
        self.assertEqual(res.data['error']['details']['retry_after_seconds'], 600)

    def test_success_resets_failure_count(self):
        for _ in range(4):
            self.login('wrong1234')
        self.assertEqual(self.login().status_code, 200)
        self.client.post(LOGOUT_URL)
        for _ in range(4):
            self.assertEqual(self.login('wrong1234').status_code, 401)  # 0부터 다시 센다


class MeTests(AccountTestBase):
    """REQ-USR-003 내 정보 설정, REQ-USR-004 회원 탈퇴."""

    def setUp(self):
        super().setUp()
        self.signup()

    def test_me_requires_login(self):
        self.client.post(LOGOUT_URL)
        res = self.client.get(ME_URL)
        self.assertEqual(res.status_code, 401)
        self.assertEqual(res.data['error']['code'], 'NOT_AUTHENTICATED')

    def test_get_me_shape(self):
        data = self.client.get(ME_URL).data['data']
        self.assertEqual(data['loss_rate'], 0.0)
        self.assertIsNone(data['transport_cost_per_km'])
        self.assertEqual(data['chat_remaining_today'], 20)

    def test_patch_changes_only_sent_fields(self):
        res = self.client.patch(ME_URL, {
            'sigungu': '청주시',
            'interest_item_ids': [self.pear.item_id],
            'transport_cost_per_km': 1800,
            'loss_rate': 2.5,
        }, format='json')
        self.assertEqual(res.status_code, 200)
        data = res.data['data']
        self.assertEqual(data['sido'], '충청북도')  # 보내지 않은 필드는 그대로
        self.assertEqual(data['sigungu'], '청주시')
        self.assertEqual([i['name'] for i in data['interest_items']], ['배'])
        self.assertEqual(data['transport_cost_per_km'], 1800)
        self.assertEqual(data['loss_rate'], 2.5)
        # 저장되었는지 다시 읽어 확인
        self.assertEqual(self.client.get(ME_URL).data['data']['sigungu'], '청주시')

    def test_patch_empty_item_list_clears_interest_items(self):
        self.client.patch(ME_URL, {'interest_item_ids': []}, format='json')
        self.assertEqual(UserInterestItem.objects.count(), 0)

    def test_patch_cannot_change_username(self):
        res = self.client.patch(ME_URL, {'username': 'other01'}, format='json')
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.data['error']['code'], 'VALIDATION_ERROR')
        self.assertTrue(User.objects.filter(username='farmer01').exists())

    def test_patch_validation(self):
        for bad in ({'loss_rate': 100}, {'loss_rate': -1}, {'transport_cost_per_km': -5},
                    {'storage_cost_per_week': 1.5}, {'interest_item_ids': [99999]}):
            res = self.client.patch(ME_URL, bad, format='json')
            self.assertEqual(res.status_code, 400, bad)

    def test_delete_with_wrong_password_keeps_data(self):
        res = self.client.delete(ME_URL, {'password': 'wrong1234'}, format='json')
        self.assertEqual(res.status_code, 401)
        self.assertEqual(res.data['error']['code'], 'INVALID_CREDENTIALS')
        self.assertTrue(User.objects.filter(username='farmer01').exists())

    def test_delete_removes_personal_data_and_ends_session(self):
        res = self.client.delete(ME_URL, {'password': 'apple2026'}, format='json')
        self.assertEqual(res.status_code, 204)
        # 삭제 후 DB를 직접 확인한다 (CASCADE는 DB가 아니라 Django가 처리한다)
        self.assertFalse(User.objects.exists())
        self.assertFalse(UserProfile.objects.exists())
        self.assertFalse(UserInterestItem.objects.exists())
        self.assertEqual(self.client.get(ME_URL).status_code, 401)
        # 품목 자체는 남아 있어야 한다
        self.assertEqual(Item.objects.count(), 2)


class CsrfTests(AccountTestBase):
    """docs/api.md 1.4: POST·PATCH·DELETE는 X-CSRFToken 헤더가 없으면 403 CSRF_FAILED."""

    def setUp(self):
        super().setUp()
        self.client = APIClient(enforce_csrf_checks=True)  # 테스트 클라이언트는 기본으로 CSRF를 건너뛴다

    def token(self):
        return self.client.cookies['csrftoken'].value

    def test_csrf_endpoint_sets_cookie(self):
        res = self.client.get('/api/auth/csrf')
        self.assertEqual(res.status_code, 204)
        self.assertIn('csrftoken', res.cookies)

    def test_anonymous_post_without_token_is_rejected(self):
        for url, body in ((SIGNUP_URL, self.signup_payload()), (LOGIN_URL, {'username': 'a', 'password': 'b'})):
            res = self.client.post(url, body, format='json')
            self.assertEqual(res.status_code, 403, url)
            self.assertEqual(res.data['error']['code'], 'CSRF_FAILED')
        self.assertFalse(User.objects.exists())

    def test_signup_with_token_succeeds(self):
        self.client.get('/api/auth/csrf')
        res = self.client.post(SIGNUP_URL, self.signup_payload(), format='json', HTTP_X_CSRFTOKEN=self.token())
        self.assertEqual(res.status_code, 201)

    def test_logged_in_patch_and_delete_need_token(self):
        self.client.get('/api/auth/csrf')
        self.client.post(SIGNUP_URL, self.signup_payload(), format='json', HTTP_X_CSRFTOKEN=self.token())
        # 로그인하면 토큰이 새로 발급되므로 쿠키의 최신 값을 쓴다
        for method in (self.client.patch, self.client.delete):
            res = method(ME_URL, {'password': 'apple2026'}, format='json')
            self.assertEqual(res.status_code, 403)
            self.assertEqual(res.data['error']['code'], 'CSRF_FAILED')
        res = self.client.patch(ME_URL, {'sigungu': '청주시'}, format='json', HTTP_X_CSRFTOKEN=self.token())
        self.assertEqual(res.status_code, 200)


class ErrorShapeTests(AccountTestBase):
    """Y02 보강: 어떤 오류든 docs/api.md 1.2절 모양({"error": {"code", "message"}})으로 나간다."""

    def assert_error(self, res, status, code):
        self.assertEqual(res.status_code, status)
        self.assertEqual(res.json()['error']['code'], code)
        self.assertIn('message', res.json()['error'])
        self.assertNotIn('detail', res.json())

    def test_405_uses_error_shape(self):
        self.assert_error(self.client.get(LOGIN_URL), 405, 'METHOD_NOT_ALLOWED')

    def test_415_uses_error_shape(self):
        res = self.client.post(LOGIN_URL, 'a=b', content_type='text/plain')
        self.assert_error(res, 415, 'UNSUPPORTED_MEDIA_TYPE')

    def test_malformed_json_is_400_validation_error(self):
        res = self.client.post(LOGIN_URL, '{"username": ', content_type='application/json')
        self.assert_error(res, 400, 'VALIDATION_ERROR')

    def test_unexpected_exception_is_500_internal_error(self):
        from unittest import mock
        with mock.patch('accounts.views.authenticate', side_effect=RuntimeError('boom')), \
                self.assertLogs('api.exceptions', 'ERROR') as logs:  # 로그가 남는지도 확인하고 출력 잡음도 막는다
            res = self.client.post(LOGIN_URL, {'username': 'farmer01', 'password': 'apple2026'}, format='json')
        self.assertIn('POST /api/auth/login', logs.output[0])
        self.assert_error(res, 500, 'INTERNAL_ERROR')
        self.assertNotIn('boom', res.content.decode())  # 내부 오류 내용은 밖으로 내보내지 않는다

    def test_array_body_is_400_not_500(self):
        self.assert_error(self.client.post(LOGIN_URL, [1, 2], format='json'), 400, 'VALIDATION_ERROR')

    def test_lock_response_has_retry_after_header(self):
        self.signup()
        self.client.post(LOGOUT_URL)
        for _ in range(5):
            self.client.post(LOGIN_URL, {'username': 'farmer01', 'password': 'wrong1234'}, format='json')
        res = self.client.post(LOGIN_URL, {'username': 'farmer01', 'password': 'apple2026'}, format='json')
        self.assert_error(res, 429, 'TOO_MANY_LOGIN_ATTEMPTS')
        self.assertEqual(res['Retry-After'], '600')

    def test_array_body_on_signup_and_me_is_400(self):
        self.assert_error(self.client.post(SIGNUP_URL, [1, 2], format='json'), 400, 'VALIDATION_ERROR')
        self.signup()
        self.assert_error(self.client.patch(ME_URL, [1, 2], format='json'), 400, 'VALIDATION_ERROR')

    def test_array_body_on_delete_me_is_401_not_500(self):
        self.signup()
        self.assert_error(self.client.delete(ME_URL, [1, 2], format='json'), 401, 'INVALID_CREDENTIALS')

    def test_throttled_has_retry_after_header(self):
        from rest_framework.exceptions import Throttled
        from api.exceptions import custom_exception_handler
        res = custom_exception_handler(Throttled(wait=30), {})
        self.assertEqual(res.status_code, 429)
        self.assertEqual(res.data['error']['code'], 'RATE_LIMITED')
        self.assertEqual(res['Retry-After'], '30')

    def test_http404_and_django_permission_denied_use_error_shape(self):
        from django.core.exceptions import PermissionDenied
        from django.http import Http404
        from api.exceptions import custom_exception_handler
        self.assertEqual(custom_exception_handler(Http404(), {}).data['error']['code'], 'NOT_FOUND')
        self.assertEqual(custom_exception_handler(PermissionDenied(), {}).data['error']['code'], 'FORBIDDEN')

    def test_unknown_url_is_json_404(self):
        self.assert_error(self.client.get('/api/no-such-path'), 404, 'NOT_FOUND')

    def test_validation_error_keeps_details(self):
        from rest_framework.exceptions import ValidationError
        from api.exceptions import custom_exception_handler
        res = custom_exception_handler(ValidationError({'size': ['너무 큽니다.']}), {})
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.data['error']['details'], {'size': ['너무 큽니다.']})

    def test_unlisted_4xx_does_not_become_internal_error(self):
        res = self.client.get('/api/auth/csrf', HTTP_ACCEPT='application/xml')
        self.assertEqual(res.status_code, 406)
        self.assertNotEqual(res.json()['error']['code'], 'INTERNAL_ERROR')

    def test_throttled_rounds_up_and_has_details(self):
        from rest_framework.exceptions import Throttled
        from api.exceptions import custom_exception_handler
        res = custom_exception_handler(Throttled(wait=0.4), {})
        self.assertEqual(res['Retry-After'], '1')
        self.assertEqual(res.data['error']['details']['retry_after_seconds'], 1)

    def test_server_error_handler_returns_json_500(self):
        from api.exceptions import server_error_handler
        res = server_error_handler(None)
        self.assertEqual(res.status_code, 500)
        self.assertEqual(res['Content-Type'], 'application/json')
        self.assertIn(b'INTERNAL_ERROR', res.content)

    def test_non_dict_validation_error_goes_to_non_field_errors(self):
        from rest_framework.exceptions import ValidationError
        from api.exceptions import custom_exception_handler
        res = custom_exception_handler(ValidationError(['x']), {})
        self.assertEqual(res.data['error']['details'], {'non_field_errors': ['x']})

    def test_unlisted_5xx_is_internal_error_and_406_is_validation_error(self):
        from rest_framework.exceptions import APIException, NotAcceptable
        from api.exceptions import custom_exception_handler

        class NotImplementedYet(APIException):
            status_code = 501

        class Unavailable(APIException):
            status_code = 503

        self.assertEqual(custom_exception_handler(NotImplementedYet(), {}).data['error']['code'], 'INTERNAL_ERROR')
        self.assertEqual(custom_exception_handler(Unavailable(), {}).data['error']['code'], 'SERVICE_UNAVAILABLE')
        self.assertEqual(custom_exception_handler(NotAcceptable(), {}).data['error']['code'], 'VALIDATION_ERROR')

    def test_throttled_without_wait_has_no_retry_after(self):
        from rest_framework.exceptions import Throttled
        from api.exceptions import custom_exception_handler
        res = custom_exception_handler(Throttled(), {})
        self.assertEqual(res.data['error']['code'], 'RATE_LIMITED')
        self.assertFalse(res.has_header('Retry-After'))
