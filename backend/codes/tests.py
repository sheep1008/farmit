from django.contrib import admin
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import (
    Holiday,
    Item,
    ItemProducingArea,
    Market,
    MarketClosure,
    WarningZone,
    WeatherStation,
)

ADMIN_MODELS = [Market, Item, WeatherStation, Holiday, WarningZone]
# 복합 PK 모델은 Django 5.2 admin이 등록을 거부한다 (codes/admin.py 주석)
COMPOSITE_PK_MODELS = [MarketClosure, ItemProducingArea]


def changelist_url(model):
    return reverse(f'admin:codes_{model._meta.model_name}_changelist')


class CodeAdminAccessTest(TestCase):
    """REQ-NFR-010: 관리자가 Django 관리 화면에서 시장·품목 코드를 관리한다."""

    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.admin_user = User.objects.create_superuser(
            username='admin-test', email='admin@example.com', password='pw-for-test-1234')
        cls.normal_user = User.objects.create_user(
            username='normal-test', email='normal@example.com', password='pw-for-test-1234')

    def test_all_models_registered(self):
        for model in ADMIN_MODELS:
            self.assertTrue(admin.site.is_registered(model), model.__name__)

    def test_superuser_changelist_ok(self):
        self.client.force_login(self.admin_user)
        for model in ADMIN_MODELS:
            with self.subTest(model=model.__name__):
                self.assertEqual(self.client.get(changelist_url(model)).status_code, 200)

    def test_anonymous_and_nonstaff_redirected(self):
        for model in ADMIN_MODELS:
            with self.subTest(model=model.__name__, who='anonymous'):
                self.assertEqual(self.client.get(changelist_url(model)).status_code, 302)
        self.client.force_login(self.normal_user)
        for model in ADMIN_MODELS:
            with self.subTest(model=model.__name__, who='normal'):
                self.assertEqual(self.client.get(changelist_url(model)).status_code, 302)

    def test_market_search_and_filter(self):
        Market.objects.create(market_id='990001', name='테스트도매', sido='서울',
                              lat='37.0', lng='127.0', is_collect=True)
        self.client.force_login(self.admin_user)
        res = self.client.get(changelist_url(Market), {'q': '테스트도매', 'is_collect__exact': '1'})
        self.assertContains(res, '테스트도매')

    def test_composite_pk_models_are_not_registered(self):
        for model in COMPOSITE_PK_MODELS:
            self.assertFalse(admin.site.is_registered(model), model.__name__)

    def test_delete_is_blocked_for_code_tables(self):
        # 관측소·품목을 지우면 CASCADE로 수집 데이터가 같이 지워지므로 admin에서 삭제를 막는다
        item = Item.objects.create(at_code='ADM01', name='관리테스트', category='과일')
        station = WeatherStation.objects.create(station_id=99901, name='테스트관측소', sido='서울', lat='37.0', lng='127.0')
        self.client.force_login(self.admin_user)
        for model, obj in [(Item, item), (WeatherStation, station)]:
            with self.subTest(model=model.__name__):
                url = reverse(f'admin:codes_{model._meta.model_name}_delete', args=[obj.pk])
                self.assertEqual(self.client.get(url).status_code, 403)
                self.assertEqual(self.client.post(url, {'post': 'yes'}).status_code, 403)
                self.assertTrue(model.objects.filter(pk=obj.pk).exists())

    def test_natural_key_is_read_only_on_change_form(self):
        Market.objects.create(market_id='990002', name='키시험도매', sido='서울', lat='37.0', lng='127.0')
        self.client.force_login(self.admin_user)
        res = self.client.get(reverse('admin:codes_market_change', args=['990002']))
        self.assertEqual(res.status_code, 200)
        self.assertNotContains(res, 'name="market_id"')
