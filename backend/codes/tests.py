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

ADMIN_MODELS = [
    Market, Item, WeatherStation, Holiday, WarningZone,
    MarketClosure, ItemProducingArea,
]
READ_ONLY_MODELS = [MarketClosure, ItemProducingArea]


def changelist_url(model):
    return reverse(f'admin:codes_{model._meta.model_name}_changelist')


def add_url(model):
    return reverse(f'admin:codes_{model._meta.model_name}_add')


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

    def test_composite_pk_models_are_read_only(self):
        self.client.force_login(self.admin_user)
        for model in READ_ONLY_MODELS:
            with self.subTest(model=model.__name__):
                self.assertEqual(self.client.get(add_url(model)).status_code, 403)
