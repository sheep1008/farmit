"""Y10 보도자료 수집·검색 테스트 (REQ-COL-007, REQ-SRC-002). 외부 사이트는 부르지 않고 가짜 HTML을 쓴다.
ES 검색 테스트는 press_release_test 인덱스를 쓰고, ES가 꺼져 있으면 건너뛴다.
"""
import io
import unittest
from datetime import date
from unittest import mock

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase, override_settings

from api.models import CollectLog
from codes.models import Item, Market
from rag import press_store, store
from rag.sources import press


def item_html(news_id, title='제목', day='2026-11-16', dept='농림축산식품부', lead='요약 &middot; 문장'):
    return (f'<li><a href="/briefing/pressReleaseView.do?newsId={news_id}&amp;pageIndex=1"><span class="text">'
            f'<strong>{title}</strong><span class="lead">{lead}</span><span class="source">'
            f'<span>{day}</span><span>{dept}</span></span></span></a></li>')


class ParseTests(SimpleTestCase):
    def test_parse_list_reads_fields_and_cleans_text(self):
        got = press.parse_list(item_html('1', title='K-포도 &quot;수출&quot;', day='2026.11.16'))
        self.assertEqual(got, [{'news_id': '1', 'title': 'K-포도 "수출"', 'summary': '요약 · 문장',
                                'published_date': '2026-11-16', 'source': '농림축산식품부',
                                'url': 'https://www.korea.kr/briefing/pressReleaseView.do?newsId=1'}])

    def test_item_without_readable_date_is_skipped(self):
        self.assertEqual(press.parse_list(item_html('2', day='날짜없음')), [])


class CollectTests(SimpleTestCase):
    def test_pages_until_short_page_for_each_dept(self):
        pages = {1: ''.join(item_html(i) for i in range(press.PAGE_SIZE)), 2: item_html(99)}
        calls = []

        def fetch(params):
            calls.append((params['repCode'], params['pageIndex']))
            return pages.get(params['pageIndex'], '')
        res = press.collect(date(2026, 11, 14), date(2026, 11, 16), fetch=fetch, interval=0)
        self.assertEqual(len(res.docs), 2 * (press.PAGE_SIZE + 1))
        self.assertEqual(calls, [('A00008', 1), ('A00008', 2), ('B00006', 1), ('B00006', 2)])
        self.assertEqual(res.calls, 4)
        self.assertTrue(all(d['license'].startswith('공공누리') for d in res.docs))

    def test_failure_of_one_dept_keeps_the_other(self):
        def fetch(params):
            if params['repCode'] == 'A00008':
                raise press.PressError('boom')
            return item_html(7, dept='농촌진흥청')
        res = press.collect(date(2026, 11, 16), date(2026, 11, 16), fetch=fetch, interval=0)
        self.assertEqual((len(res.docs), res.errors), (1, 1))

    def test_other_dept_and_unreadable_page_are_handled(self):
        res = press.collect(date(2026, 11, 16), date(2026, 11, 16), depts=['A00008'], interval=0,
                            fetch=lambda p: item_html(1, dept='국토교통부'))
        self.assertEqual(res.docs, [])
        broken = press.collect(date(2026, 11, 16), date(2026, 11, 16), depts=['A00008'], interval=0,
                               fetch=lambda p: '<a href="/briefing/pressReleaseView.do?newsId=1">x</a>')
        self.assertEqual((broken.docs, broken.errors), ([], 1))

    def test_request_is_polite(self):
        self.assertEqual(press.INTERVAL, 1.0)
        self.assertNotIn('@', press.USER_AGENT)   # 개인 연락처를 넣지 않는다
        press.USER_AGENT.encode('ascii')          # HTTP 헤더는 latin-1만 가능 (한글이면 요청이 실패한다)


class CommandTests(TestCase):
    def run_cmd(self, result, **kw):
        out = io.StringIO()
        with mock.patch('chat.management.commands.press_collect.press.collect', return_value=result), \
                mock.patch('chat.management.commands.press_collect.press_store') as ps:
            ps.index_docs.side_effect = lambda docs: len(docs)
            call_command('press_collect', stdout=out, stderr=io.StringIO(), **kw)
        return ps

    def test_logs_success_to_collect_log(self):
        docs = [{'news_id': '1'}, {'news_id': '2'}]
        self.run_cmd(press.PressResult(docs=docs, calls=2), days=1)
        log = CollectLog.objects.get(source='press')
        self.assertEqual((log.status, log.row_count, log.api_calls), ('success', 2, 2))

    def test_total_failure_logs_fail(self):
        with self.assertRaises(SystemExit):
            self.run_cmd(press.PressResult(docs=[], calls=2, errors=2), days=1)
        self.assertEqual(CollectLog.objects.get(source='press').status, 'fail')

    def test_partial_failure_exits_nonzero_and_logs_partial(self):
        with self.assertRaises(SystemExit):
            self.run_cmd(press.PressResult(docs=[{'news_id': '1'}], calls=2, errors=1), days=1)
        self.assertEqual(CollectLog.objects.get(source='press').status, 'partial')


class SearchApiTests(TestCase):
    fixtures = []

    def test_requires_q(self):
        res = self.client.get('/api/search')
        self.assertEqual((res.status_code, res.json()['error']['code']), (400, 'VALIDATION_ERROR'))

    def test_bad_type_and_size(self):
        for qs in ('type=x', 'size=0', 'page=abc'):
            res = self.client.get(f'/api/search?q=a&{qs}')
            self.assertEqual((res.status_code, res.json()['error']['code']), (400, 'INVALID_PARAMETER'), qs)

    def test_page_window_is_capped(self):
        res = self.client.get('/api/search?q=a&page=1001&size=10')
        self.assertEqual((res.status_code, res.json()['error']['code']), (400, 'INVALID_PARAMETER'))
        self.assertEqual(self.client.get('/api/search?q=a&size=101').status_code, 400)

    def test_market_search_uses_same_scope_as_markets_api(self):
        Market.objects.create(market_id='9', name='천안참고', sido='충남', lat=1, lng=1, is_collect=False)
        self.assertEqual(self.client.get('/api/search?q=천안&type=market').json()['data'], [])

    def test_default_type_is_press(self):
        with mock.patch('api.views.press_store.search', return_value=(0, [])):
            self.assertEqual(self.client.get('/api/search?q=a').json()['meta']['type'], 'press')

    def test_press_returns_title_date_link(self):
        hit = {'title': '사과 수급 안정', 'summary': 's', 'published_date': '2026-11-16', 'source': '농림축산식품부',
               'url': 'https://www.korea.kr/briefing/pressReleaseView.do?newsId=1', 'news_id': '1'}
        with mock.patch('api.views.press_store.search', return_value=(1, [hit])) as m:
            res = self.client.get('/api/search?q=사과&type=press&page=2&size=5')
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(set(body['data'][0]), {'title', 'summary', 'published_date', 'source', 'url'})
        self.assertEqual((body['meta']['total'], body['meta']['page']), (1, 2))
        m.assert_called_once_with('사과', size=5, offset=5)

    def test_press_no_result_is_empty_list(self):
        with mock.patch('api.views.press_store.search', return_value=(0, [])):
            res = self.client.get('/api/search?q=없는말')
        self.assertEqual((res.status_code, res.json()['data']), (200, []))

    def test_press_es_down_is_503(self):
        with mock.patch('api.views.press_store.search', side_effect=store.StoreUnavailable('x')):
            res = self.client.get('/api/search?q=사과')
        self.assertEqual((res.status_code, res.json()['error']['code']), (503, 'SERVICE_UNAVAILABLE'))

    def test_item_and_market_partial_name(self):
        Item.objects.create(item_id=1, name='청양고추', category='채소')
        Market.objects.create(market_id='1', name='천안농수산물도매시장', sido='충남', lat=36.8, lng=127.1, is_collect=True)
        res = self.client.get('/api/search?q=고추&type=item').json()
        self.assertEqual([d['name'] for d in res['data']], ['청양고추'])
        res = self.client.get('/api/search?q=천안&type=market').json()
        self.assertEqual([d['name'] for d in res['data']], ['천안농수산물도매시장'])


def _es_up():
    try:
        store.get_es().info()
        return True
    except Exception:
        return False


@unittest.skipUnless(_es_up(), 'Elasticsearch가 꺼져 있다')
@override_settings(PRESS_INDEX='press_release_test')
class PressSearchEsTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        press_store.ensure_index(recreate=True)
        press_store.index_docs([
            {'news_id': '1', 'title': '사과 수급 안정 대책', 'summary': '사과 가격', 'published_date': '2026-11-10',
             'source': '농림축산식품부', 'url': 'u1', 'license': 'l'},
            {'news_id': '2', 'title': '고병원성 조류인플루엔자 확진', 'summary': '산란계 농장', 'published_date': '2026-11-13',
             'source': '농림축산식품부', 'url': 'u2', 'license': 'l'}])

    @classmethod
    def tearDownClass(cls):
        store.get_es().indices.delete(index='press_release_test', ignore_unavailable=True)
        super().tearDownClass()

    def test_partial_word_with_particle_matches(self):
        total, hits = press_store.search('조류인플루엔자')
        self.assertEqual([h['news_id'] for h in hits], ['2'])

    def test_part_of_a_word_matches(self):
        """낱말 일부만 넣어도 찾는다 (K55). nori는 '인플루'를 '인'·'플'로 쪼개 형태소 검색으로는 0건이다"""
        for q in ('인플루', '플루엔자', '조류인플'):
            total, hits = press_store.search(q)
            self.assertEqual((total, [h['news_id'] for h in hits]), (1, ['2']), q)

    def test_every_word_must_match(self):
        self.assertEqual(press_store.search('사과 인플루')[0], 0)       # 한 낱말만 맞으면 찾지 않는다
        self.assertEqual(press_store.search('산란계 인플루')[0], 1)     # 요약의 낱말 + 제목의 부분 낱말
        self.assertEqual(press_store.search('없는말')[0], 0)

    def test_same_news_id_is_overwritten_not_duplicated(self):
        press_store.index_docs([{'news_id': '1', 'title': '사과 수급 안정 대책(수정)', 'summary': '', 'published_date': '2026-11-10',
                                 'source': '농림축산식품부', 'url': 'u1', 'license': 'l'}])
        total, _ = press_store.search('사과')
        self.assertEqual(total, 1)


@unittest.skipUnless(_es_up(), 'Elasticsearch가 꺼져 있다')
@override_settings(PRESS_INDEX='press_release_test2')
class CollectToSearchTests(TestCase):
    """수집 명령 → 실제 ES 색인 → 검색 API까지 (REQ-COL-007, REQ-SRC-002)"""

    def tearDown(self):
        store.get_es().indices.delete(index='press_release_test2', ignore_unavailable=True)

    def test_collected_press_is_searchable(self):
        docs = [{'news_id': '5', 'title': '배추 수급 안정', 'summary': '김장 배추', 'published_date': '2026-11-16',
                 'source': '농림축산식품부', 'url': 'u5', 'license': 'l'}]
        with mock.patch('chat.management.commands.press_collect.press.collect',
                        return_value=press.PressResult(docs=docs, calls=1)):
            call_command('press_collect', days=1, stdout=io.StringIO())
        body = self.client.get('/api/search?q=배추').json()
        self.assertEqual([d['url'] for d in body['data']], ['u5'])
