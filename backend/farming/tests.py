"""Y14 재배 API 테스트 (REQ-RAG-001~007, REQ-COL-006).

외부 호출(농사로·위키백과·Claude·ES)은 하지 않는다: Fetcher.get, glossary 함수, rag.retrieve.search, rag.llm.complete를 가짜로 바꾼다.
"""
import json
from datetime import date
from unittest import mock

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from accounts.models import UserProfile
from chat.models import ChatMessage, ChatSession
from codes.models import Item
from farming import collect, glossary
from farming import schedule as sch
from farming.models import FarmSchedule
from rag.dose_filter import DOSE_TOKEN
from rag.llm import LlmError, LlmResult
from rag.sources.http import SourceError


def row(task, sm, sp, em, ep, stage='생육과정(주요농작업)'):
    return {'task_name': task, 'stage': stage, 'start_month': sm, 'start_period': sp, 'end_month': em, 'end_period': ep}


APPLE_ROWS = [
    row('정지, 전정', 1, '하', 2, '하'),
    row('수분', 3, '상', 4, '하'),
    row('꽃솎기, 열매솎기', 5, '상', 5, '하'),
    row('웃거름', 5, '중', 5, '하'),
    row('수확', 9, '중', 11, '상'),
    row('개화', 4, '중', 5, '상'),
    row('병해충 발생', 4, '하', 9, '중'),
    row('휴면', 12, '상', 2, '하'),        # 해를 넘는 행
    row('시기정보 참고', 1, '상', 12, '하', stage='재배환경'),   # 생육과정이 아니라 쓰지 않는다
]


class Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.apple = Item.objects.create(at_code='0601', name='사과', category='과실류')
        cls.cabbage = Item.objects.create(at_code='0801', name='토마토', category='과채류')
        cls.banana = Item.objects.create(at_code='0901', name='바나나', category='과실류')
        FarmSchedule.objects.bulk_create([FarmSchedule(item=cls.apple, **r) for r in APPLE_ROWS])
        FarmSchedule.objects.create(item=cls.cabbage, **row('아주심기', 4, '중', 5, '하'))

    def setUp(self):
        cache.clear()
        self.client = APIClient()


class ScheduleCalcTests(TestCase):
    def test_task_kind_splits_by_comma_parts(self):
        """생육 단계·주의 시기·농작업 구분 ("발아기, 모기르기"는 농작업)"""
        self.assertEqual(sch.task_kind('개화'), sch.KIND_GROWTH)
        self.assertEqual(sch.task_kind('발아, 전엽'), sch.KIND_GROWTH)
        self.assertEqual(sch.task_kind('병해충 발생'), sch.KIND_CAUTION)
        self.assertEqual(sch.task_kind('발아기, 모기르기'), sch.KIND_WORK)
        self.assertEqual(sch.task_kind('웃거름'), sch.KIND_WORK)

    def test_merge_same_task_joins_overlapping_but_not_year_wrap(self):
        rows = [row('수확', 6, '상', 7, '중'), row('수확', 7, '하', 8, '중'), row('수확', 11, '상', 2, '하')]
        merged = sch.merge_same_task(rows)
        self.assertEqual([(r['start_month'], r['end_month']) for r in merged], [(6, 8), (11, 2)])

    def test_today_index_and_condition_months(self):
        self.assertEqual(sch.today_index(date(2026, 1, 5)), 0)
        self.assertEqual(sch.today_index(date(2026, 11, 16)), 31)
        self.assertEqual(sch.today_index(date(2026, 12, 31)), 35)
        self.assertEqual(sch.condition_months('3~5월'), [3, 4, 5])
        self.assertEqual(sch.condition_months('겨울'), [1, 2, 12])
        self.assertEqual(sch.condition_months('8월에 수확'), [8])
        self.assertEqual(sch.parse_condition('봄에 심는 채소'), {'task': '심기', 'months': [3, 4, 5], 'category': '채소'})

    def test_gantt_splits_year_wrap_bar_in_two(self):
        rows = [dict(row('휴면', 12, '상', 2, '하'), kind='생육 단계', period='x')]
        bars = sch.gantt_bars(rows)
        self.assertEqual([(b['start'], b['end']) for b in bars], [(33, 36), (0, 6)])


class MonthlyTests(Base):
    URL = '/api/farming/monthly'

    def test_month_shows_start_continue_next_growth_and_caution(self):
        """REQ-RAG-002: 품목을 고르면 이번 달 할 일(시작·계속·다음 달)·생육 상태·주의 시기가 표시된다"""
        d = self.client.get(self.URL, {'item_id': self.apple.item_id, 'month': 4}).json()['data']
        self.assertEqual([e['task'] for e in d['start']], [])
        self.assertEqual([e['task'] for e in d['continue']], ['수분'])
        self.assertEqual([e['task'] for e in d['next']], ['꽃솎기, 열매솎기', '웃거름'])
        self.assertEqual([e['task'] for e in d['growth']], ['개화'])
        self.assertEqual([e['task'] for e in d['caution']], ['병해충 발생'])
        d3 = self.client.get(self.URL, {'item_id': self.apple.item_id, 'month': 3}).json()['data']
        self.assertEqual([e['task'] for e in d3['start']], ['수분'])

    def test_non_growth_stage_rows_are_not_used(self):
        d = self.client.get(self.URL, {'item_id': self.apple.item_id, 'month': 7}).json()['data']
        self.assertNotIn('시기정보 참고', [e['task'] for k in ('start', 'continue', 'next') for e in d[k]])

    def test_default_month_is_today_kst(self):
        with mock.patch('farming.views._today_kst', return_value=date(2026, 5, 3)):
            d = self.client.get(self.URL, {'item_id': self.apple.item_id}).json()['data']
        self.assertEqual(d['month'], 5)

    def test_item_without_schedule_is_200_with_message(self):
        res = self.client.get(self.URL, {'item_id': self.banana.item_id, 'month': 4})
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertFalse(body['data']['available'])
        self.assertEqual(body['data']['start'], [])
        self.assertIn('message', body['meta'])

    def test_validation_and_not_found(self):
        self.assertEqual(self.client.get(self.URL).status_code, 400)
        self.assertEqual(self.client.get(self.URL, {'item_id': 'x'}).status_code, 400)
        self.assertEqual(self.client.get(self.URL, {'item_id': self.apple.item_id, 'month': 13}).status_code, 400)
        self.assertEqual(self.client.get(self.URL, {'item_id': self.apple.item_id, 'month': '²'}).status_code, 400)
        res = self.client.get(self.URL, {'item_id': 99999})
        self.assertEqual((res.status_code, res.json()['error']['code']), (404, 'NOT_FOUND'))

    def test_no_login_needed_and_few_queries(self):
        with self.assertNumQueries(2):    # 품목 1 + 일정 1
            self.assertEqual(self.client.get(self.URL, {'item_id': self.apple.item_id, 'month': 4}).status_code, 200)


class CalendarTests(Base):
    def test_bars_have_slots_and_today_line(self):
        """REQ-RAG-003: 월 × 상·중·하순 막대와 현재 시점 선(today_index)이 표시된다"""
        with mock.patch('farming.views._today_kst', return_value=date(2026, 11, 16)):
            body = self.client.get('/api/farming/calendar', {'item_id': self.apple.item_id}).json()
        self.assertEqual(body['meta']['today_index'], 31)
        self.assertEqual(body['meta']['slots'], 36)
        bars = {b['task']: b for b in body['data']['bars']}
        self.assertEqual((bars['수분']['start'], bars['수분']['end']), (6, 12))   # 3월 상순~4월 하순
        self.assertEqual(sum(1 for b in body['data']['bars'] if b['task'] == '휴면'), 2)
        self.assertNotIn('시기정보 참고', bars)

    def test_no_schedule_is_empty_bars(self):
        d = self.client.get('/api/farming/calendar', {'item_id': self.banana.item_id}).json()['data']
        self.assertEqual((d['available'], d['bars']), (False, []))


class SummaryGuideTests(Base):
    def test_summary_counts_and_schedule(self):
        """REQ-RAG-006: 주요 병해충 수·현장기술지원 건수·농작업일정 요약"""
        with mock.patch('farming.doc_stats.counts', return_value={'사과': {'pests': 68, 'fieldtech': 8}}):
            d = self.client.get('/api/farming/summary', {'item_id': self.apple.item_id}).json()['data']
        self.assertEqual((d['pest_count'], d['fieldtech_count']), (68, 8))
        self.assertEqual(d['schedule']['task_count'], 5)       # 농작업만: 전정·수분·꽃솎기·웃거름·수확
        self.assertEqual(d['schedule']['first_task']['task'], '정지, 전정')

    def test_summary_item_without_docs(self):
        with mock.patch('farming.doc_stats.counts', return_value={}):
            d = self.client.get('/api/farming/summary', {'item_id': self.banana.item_id}).json()['data']
        self.assertEqual((d['pest_count'], d['schedule']['available']), (0, False))

    def test_guide_lists_work_in_start_order(self):
        """REQ-RAG-004: 단계별(시작 시기 순) 작업 요약"""
        d = self.client.get('/api/farming/guide', {'item_id': self.apple.item_id}).json()['data']
        self.assertEqual([s['task'] for s in d['steps']], ['정지, 전정', '수분', '꽃솎기, 열매솎기', '웃거름', '수확'])


class SearchTests(Base):
    URL = '/api/farming/search'

    def test_condition_returns_matching_items_with_schedule(self):
        """REQ-RAG-005: 조건을 입력하면 맞는 품목(최대 6개)과 일정이 표시된다"""
        d = self.client.get(self.URL, {'q': '봄에 심는 채소'}).json()
        self.assertEqual([c['name'] for c in d['data']], ['토마토'])
        self.assertEqual(d['data'][0]['schedule'][0], {'task': '아주심기', 'period': '4월 중순~5월 하순'})
        self.assertEqual(d['meta']['condition']['months'], [3, 4, 5])

    def test_category_and_task_filter(self):
        names = [c['name'] for c in self.client.get(self.URL, {'q': '가을 수확 과일'}).json()['data']]
        self.assertEqual(names, ['사과'])
        self.assertEqual(self.client.get(self.URL, {'q': '봄에 심는 과일'}).json()['data'], [])

    def test_max_six_results(self):
        for i in range(8):
            item = Item.objects.create(at_code=f'09{i:02d}9', name=f'채소{i}', category='엽경채류')
            FarmSchedule.objects.create(item=item, **row('파종', 3, '상', 4, '상'))
        self.assertEqual(len(self.client.get(self.URL, {'q': '3월 파종 채소'}).json()['data']), 6)

    def test_needs_time_or_task(self):
        self.assertEqual(self.client.get(self.URL, {'q': '맛있는 채소'}).status_code, 400)
        self.assertEqual(self.client.get(self.URL).status_code, 400)


class GlossaryTests(Base):
    URL = '/api/farming/glossary'

    def test_dictionary_first_then_wikipedia(self):
        """REQ-RAG-007: 농업용어사전 우선, 없으면 위키백과. 풀이와 출처 표시"""
        dic = {'definition': '풀이', 'source': glossary.DIC_LABEL, 'url': '', 'license': glossary.DIC_LICENSE}
        wiki = {'definition': '위키 풀이', 'source': glossary.WIKI_LABEL, 'url': 'https://ko.wikipedia.org/wiki/x',
                'license': glossary.WIKI_LICENSE}
        with mock.patch('farming.glossary.from_dictionary', return_value=dic), \
                mock.patch('farming.glossary.from_wikipedia', return_value=wiki) as w:
            d = self.client.get(self.URL, {'q': '분생포자'}).json()['data']
            self.assertEqual((d['found'], d['source']), (True, glossary.DIC_LABEL))
            w.assert_not_called()
        with mock.patch('farming.glossary.from_dictionary', return_value=None), \
                mock.patch('farming.glossary.from_wikipedia', return_value=wiki):
            d = self.client.get(self.URL, {'q': '스마트팜'}).json()['data']
            self.assertEqual((d['source'], d['url']), (glossary.WIKI_LABEL, wiki['url']))

    def test_not_found_is_200_found_false_and_cached(self):
        with mock.patch('farming.glossary.from_dictionary', return_value=None) as a, \
                mock.patch('farming.glossary.from_wikipedia', return_value=None):
            for _ in range(2):
                d = self.client.get(self.URL, {'q': '없는말'}).json()['data']
            self.assertEqual((d['found'], d['term']), (False, '없는말'))
            self.assertEqual(a.call_count, 1)

    def test_validation(self):
        self.assertEqual(self.client.get(self.URL).status_code, 400)
        self.assertEqual(self.client.get(self.URL, {'q': 'a' * 31}).status_code, 400)

    def test_dictionary_without_key_returns_none(self):
        with mock.patch.dict('os.environ', {'NONGSARO_API_KEY': ''}):
            self.assertIsNone(glossary.from_dictionary('분생포자'))

    def test_wikipedia_disambiguation_is_not_used(self):
        body = json.dumps({'type': 'disambiguation', 'extract': '여러 뜻'}).encode()
        with mock.patch('urllib.request.urlopen') as op:
            op.return_value.__enter__.return_value.read.return_value = body
            self.assertIsNone(glossary.from_wikipedia('배'))


LIST_XML = ('<response><header><resultCode>00</resultCode></header><body><items>'
            '<item><cntntsNo>1</cntntsNo><sj>사과</sj></item><item><cntntsNo>2</cntntsNo><sj>토마토(촉성재배)</sj></item>'
            '<item><cntntsNo>3</cntntsNo><sj>토마토(보통재배)</sj></item></items></body></response>')
ERA_XML = ('<response><header><resultCode>00</resultCode></header><body><items>'
           '<item><beginEra>상</beginEra><beginMon>3</beginMon><endEra>하</endEra><endMon>4</endMon>'
           '<infoSeCodeNm>생육과정(주요농작업)</infoSeCodeNm><opertNm><![CDATA[수분<br/>작업]]></opertNm></item>'
           '<item><beginEra></beginEra><beginMon>3</beginMon><endEra>하</endEra><endMon>4</endMon><opertNm>시기 없음</opertNm></item>'
           '</items></body></response>')


class CollectTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.apple = Item.objects.create(at_code='0601', name='사과', category='과실류')
        cls.tomato = Item.objects.create(at_code='0801', name='토마토', category='과채류')
        Item.objects.create(at_code='0901', name='바나나', category='과실류')

    def fake_get(self, url, params, cache_name=None, refresh=False, retries=3):
        return LIST_XML if 'workScheduleLst' in url else ERA_XML

    def run_collect(self):
        with mock.patch.dict('os.environ', {'NONGSARO_WORKPLAN_KEY': 'k'}), \
                mock.patch('rag.sources.http.Fetcher.get', self.fake_get), \
                mock.patch('rag.sources.http.Fetcher.save'):
            return collect.collect(log=lambda *_: None)

    def test_saves_rows_per_item_and_skips_items_without_schedule(self):
        """REQ-COL-006: 품목 이름과 맞는 대표 일정의 시기정보를 farm_schedule에 저장한다"""
        r = self.run_collect()
        self.assertEqual(r['items'], 2)
        self.assertEqual(r['skipped'], ['바나나'])
        saved = FarmSchedule.objects.get(item=self.apple)
        self.assertEqual((saved.task_name, saved.start_period, saved.end_month), ('수분 작업', '상', 4))   # 태그 제거, 시기 없는 행 제외
        self.assertEqual(FarmSchedule.objects.count(), 2)

    def test_rerun_replaces_rows_without_duplicates(self):
        self.run_collect()
        self.run_collect()
        self.assertEqual(FarmSchedule.objects.filter(item=self.apple).count(), 1)

    def test_representative_schedule_prefers_exact_then_normal_cultivation(self):
        schedules = [{'id': '2', 'name': '토마토(촉성재배)'}, {'id': '3', 'name': '토마토(보통재배)'}]
        self.assertEqual(collect.pick_schedule('토마토', schedules)['id'], '3')
        self.assertIsNone(collect.pick_schedule('수박', schedules))

    def test_missing_key_stops(self):
        with mock.patch.dict('os.environ', {'NONGSARO_WORKPLAN_KEY': ''}):
            with self.assertRaises(SourceError):
                collect.collect(log=print)

    def test_domain_mismatch_stops(self):
        bad = '<response><header><resultCode>15</resultCode></header></response>'
        with mock.patch.dict('os.environ', {'NONGSARO_WORKPLAN_KEY': 'k'}), \
                mock.patch('rag.sources.http.Fetcher.get', return_value=bad):
            with self.assertRaises(SourceError):
                collect.collect(log=print)


EVIDENCE = [
    {'n': 1, 'title': '사과 탄저병 (병)', 'source_label': 'NCPMS', 'source_type': 'ncpms_pest', 'url': 'u1',
     'license': 'L', 'text': '열매에 둥근 갈색 반점', 'chunk_id': 'a:0', 'doc_id': 'a'},
    {'n': 2, 'title': '사과 갈색무늬병 (병)', 'source_label': 'NCPMS', 'source_type': 'ncpms_pest', 'url': '',
     'license': 'L', 'text': '잎에 갈색 무늬', 'chunk_id': 'b:0', 'doc_id': 'b'},
]


def llm_result(data):
    return LlmResult(text=json.dumps(data, ensure_ascii=False), model='m', input_tokens=100, output_tokens=40, latency_ms=5)


class DiagnoseTests(Base):
    URL = '/api/farming/diagnose'

    def setUp(self):
        super().setUp()
        self.user = User.objects.create_user('farmer', password='pw12345678!')
        UserProfile.objects.create(user=self.user, sido='충남', sigungu='천안시')
        self.client.force_login(self.user)
        p1 = mock.patch('rag.retrieve.search', return_value=EVIDENCE)
        p2 = mock.patch('rag.llm.complete')
        self.search, self.complete = p1.start(), p2.start()
        self.addCleanup(p1.stop)
        self.addCleanup(p2.stop)
        self.complete.return_value = llm_result({'candidates': [
            {'name': '탄저병', 'matching': '열매 반점', 'distinguish': '움푹 들어감', 'action': '병든 열매 제거', 'evidence': [1]},
            {'name': '갈색무늬병', 'matching': '잎 무늬', 'distinguish': '', 'action': '낙엽 제거', 'evidence': [2, 9]},
            {'name': '근거 없는 병', 'matching': 'x', 'distinguish': '', 'action': 'y', 'evidence': [9]},
            {'name': '셋째', 'matching': 'x', 'distinguish': '', 'action': 'y', 'evidence': [1]},
            {'name': '넷째', 'matching': 'x', 'distinguish': '', 'action': 'y', 'evidence': [1]},
        ]})

    def post(self, **body):
        return self.client.post(self.URL, {'item_id': self.apple.item_id, 'symptom': '열매에 둥근 반점', **body}, format='json')

    def test_returns_up_to_three_candidates_with_evidence_and_sources(self):
        """REQ-RAG-001: 증상을 입력하면 후보별 맞는 증상·구분점·대응 요약·근거가 표시된다 (최대 3개, 근거 번호 검사)"""
        res = self.post()
        self.assertEqual(res.status_code, 200)
        d = res.json()['data']
        self.assertEqual([c['name'] for c in d['candidates']], ['탄저병', '갈색무늬병', '셋째'])   # 근거 없는 후보는 빠진다
        self.assertEqual(d['candidates'][1]['evidence'], [2])                                      # 목록 밖 번호는 지운다
        self.assertEqual([s['n'] for s in d['sources']], [1, 2])
        self.assertEqual(d['sources'][0]['url'], 'u1')
        self.assertIn('disclaimer', d)
        self.assertEqual(self.search.call_args.kwargs['crop'], '사과')
        self.assertEqual(self.search.call_args.kwargs['source_types'], ['ncpms_pest', 'fieldtech'])

    def test_dose_text_is_masked(self):
        self.complete.return_value = llm_result({'candidates': [
            {'name': '탄저병', 'matching': '반점', 'distinguish': '',
             'action': '베노밀 수화제를 물 20L당 20g 희석해 살포합니다.', 'evidence': [1]}]})
        action = self.post().json()['data']['candidates'][0]['action']
        self.assertIn(DOSE_TOKEN, action)
        self.assertNotIn('20g', action)

    def test_counts_toward_chat_daily_limit_and_is_saved_in_history(self):
        """채팅 한도에 포함: 진단 1번 = 질문 1번. 대화 기록에도 남는다"""
        before = ChatMessage.objects.filter(role='user').count()
        res = self.post()
        self.assertEqual(res.json()['meta']['remaining_today'], 19)
        self.assertEqual(ChatMessage.objects.filter(role='user').count(), before + 1)
        self.assertTrue(ChatMessage.objects.filter(role='assistant', intent='병해충', sources__isnull=False).exists())

    @override_settings(LLM_DAILY_LIMIT=1)
    def test_daily_limit_429(self):
        self.assertEqual(self.post().status_code, 200)
        res = self.post()
        self.assertEqual((res.status_code, res.json()['error']['code']), (429, 'CHAT_DAILY_LIMIT'))
        self.assertIn('Retry-After', res)

    def test_llm_failure_returns_502_and_gives_back_the_count(self):
        self.complete.side_effect = LlmError('unavailable', 'x')
        res = self.post()
        self.assertEqual((res.status_code, res.json()['error']['code']), (502, 'UPSTREAM_ERROR'))
        self.assertEqual(ChatSession.objects.filter(user=self.user).count(), 0)
        self.complete.side_effect = LlmError('timeout', 'x')
        self.assertEqual(self.post().status_code, 504)

    def test_no_evidence_means_no_llm_call(self):
        self.search.return_value = []
        d = self.post().json()['data']
        self.assertEqual(d['candidates'], [])
        self.assertIn('message', d)
        self.complete.assert_not_called()

    def test_auth_csrf_and_validation(self):
        anon = APIClient()
        self.assertEqual(anon.post(self.URL, {}, format='json').status_code, 401)
        csrf = APIClient(enforce_csrf_checks=True)
        csrf.force_login(self.user)
        res = csrf.post(self.URL, {'item_id': self.apple.item_id, 'symptom': 'x'}, format='json')
        self.assertEqual((res.status_code, res.json()['error']['code']), (403, 'CSRF_FAILED'))
        self.assertEqual(self.post(symptom='').status_code, 400)
        self.assertEqual(self.post(symptom='a' * 301).status_code, 400)
        self.assertEqual(self.post(item_id=99999).status_code, 404)


class ErrorShapeTests(Base):
    def test_item_errors_on_every_item_api(self):
        """공통 오류: item_id 없음·형식 오류는 400 VALIDATION_ERROR, 없는 품목은 404 NOT_FOUND"""
        for name in ('monthly', 'calendar', 'summary', 'guide'):
            url = f'/api/farming/{name}'
            res = self.client.get(url)
            self.assertEqual((res.status_code, res.json()['error']['code']), (400, 'VALIDATION_ERROR'), name)
            self.assertEqual(self.client.get(url, {'item_id': 'x'}).status_code, 400, name)
            res = self.client.get(url, {'item_id': 99999})
            self.assertEqual((res.status_code, res.json()['error']['code']), (404, 'NOT_FOUND'), name)

    def test_guide_without_schedule(self):
        d = self.client.get('/api/farming/guide', {'item_id': self.banana.item_id}).json()
        self.assertEqual((d['data']['available'], d['data']['steps']), (False, []))
        self.assertIn('message', d['meta'])

    def test_validation_error_code_on_search_and_glossary(self):
        for url in ('/api/farming/search', '/api/farming/glossary'):
            self.assertEqual(self.client.get(url).json()['error']['code'], 'VALIDATION_ERROR')


class CommandTests(TestCase):
    def test_command_runs_collect_and_prints_summary(self):
        from io import StringIO
        from django.core.management import call_command
        from django.core.management.base import CommandError
        out = StringIO()
        with mock.patch('farming.management.commands.collect_farm_schedule.collect',
                        return_value={'items': 2, 'rows': 10, 'calls': 5, 'skipped': ['바나나']}) as c:
            call_command('collect_farm_schedule', '--refresh', stdout=out)
        self.assertTrue(c.call_args.kwargs['refresh'])
        self.assertIn('품목 2개, 행 10개', out.getvalue())
        with mock.patch('farming.management.commands.collect_farm_schedule.collect', side_effect=SourceError('x')):
            with self.assertRaises(CommandError):
                call_command('collect_farm_schedule')


class DiagnoseErrorTests(DiagnoseTests):  # noqa
    """DiagnoseTests의 준비(로그인·가짜 검색·LLM)를 이어 쓴다 (상속된 테스트는 다시 돌아가지만 짧다)."""

    def test_store_unavailable_is_503_and_gives_back_the_count(self):
        from rag.store import StoreUnavailable
        self.search.side_effect = StoreUnavailable('x')
        res = self.post()
        self.assertEqual((res.status_code, res.json()['error']['code']), (503, 'SERVICE_UNAVAILABLE'))
        self.assertEqual(ChatSession.objects.filter(user=self.user).count(), 0)

    def test_item_without_crop_data_is_400(self):
        etc = Item.objects.create(at_code='9999', name='기타', category='과실류')
        res = self.post(item_id=etc.item_id)
        self.assertEqual((res.status_code, res.json()['error']['code']), (400, 'VALIDATION_ERROR'))


class ReviewFixTests(DiagnoseTests):
    """reviewer 지적 사항 (Y14 1차 검사)."""

    def test_dose_without_known_pesticide_name_is_masked(self):
        from farming.diagnose import _clean
        for text in ('만코제브 500배로 뿌려 주세요.', '델란 1000배 살포', '물 20L에 20g을 타서 살포하세요.'):
            self.assertIn(DOSE_TOKEN, _clean(text), text)
        self.assertEqual(_clean('병든 열매를 따서 땅에 묻습니다.'), '병든 열매를 따서 땅에 묻습니다.')

    def test_odd_evidence_formats_do_not_crash(self):
        self.complete.return_value = llm_result({'candidates': [
            {'name': 'a', 'evidence': 1, 'matching': 'x'},            # 정수 하나
            {'name': 'b', 'evidence': [[1]], 'matching': 'x'},        # 중첩
            {'name': 'c', 'evidence': [True], 'matching': 'x'},       # True는 1번이 아니다
            {'name': 'd', 'evidence': [2], 'matching': 'x'}]})
        res = self.post()
        self.assertEqual(res.status_code, 200)
        self.assertEqual([c['name'] for c in res.json()['data']['candidates']], ['a', 'd'])

    def test_unexpected_error_gives_back_the_count_and_is_500(self):
        self.search.side_effect = RuntimeError('boom')
        client = APIClient(raise_request_exception=False)
        client.force_login(self.user)
        res = client.post(self.URL, {'item_id': self.apple.item_id, 'symptom': '반점'}, format='json')
        self.assertEqual(res.status_code, 500)
        self.assertEqual(ChatSession.objects.filter(user=self.user).count(), 0)

    def test_no_evidence_does_not_use_the_daily_limit(self):
        self.search.return_value = []
        res = self.post()
        self.assertEqual(res.json()['meta']['remaining_today'], 20)
        self.assertEqual(ChatSession.objects.filter(user=self.user).count(), 0)

    def test_glossary_is_rate_limited(self):
        with override_settings(), mock.patch('farming.views.GlossaryThrottle.THROTTLE_RATES',
                                             {'glossary': '2/min'}, create=True), \
                mock.patch('farming.glossary.lookup', return_value={'term': 'x', 'found': False}):
            codes = [APIClient().get('/api/farming/glossary', {'q': 'x'}).status_code for _ in range(3)]
        self.assertEqual(codes, [200, 200, 429])

    def test_summary_message_when_no_schedule_and_growth_only_counts_as_available(self):
        d = self.client.get('/api/farming/summary', {'item_id': self.banana.item_id}).json()
        self.assertIn('message', d['meta'])
        FarmSchedule.objects.create(item=self.banana, **row('개화', 4, '상', 4, '하'))
        d = self.client.get('/api/farming/summary', {'item_id': self.banana.item_id}).json()
        self.assertTrue(d['data']['schedule']['available'])
        self.assertNotIn('message', d['meta'])

    def test_search_uses_constant_queries_and_skips_non_work_rows(self):
        for i in range(10):
            item = Item.objects.create(at_code=f'08{i:02d}8', name=f'엽채{i}', category='엽경채류')
            FarmSchedule.objects.bulk_create([FarmSchedule(item=item, **row('파종', 3, '상', 4, '상')),
                                              FarmSchedule(item=item, **row('병해충 발생', 3, '상', 9, '하'))])
        with self.assertNumQueries(2):    # 품목 1 + 일정 1
            d = self.client.get('/api/farming/search', {'q': '3월 채소'}).json()['data']
        self.assertEqual(len(d), 6)
        self.assertTrue(all(s['task'] == '파종' or s['task'] == '아주심기' for c in d for s in c['schedule']))
        self.assertEqual(sch.condition_months('봄동 심는 시기'), [])

    def test_merge_respects_gap_between_periods(self):
        rows = [row('수확', 3, '상', 3, '상'), row('수확', 4, '하', 5, '하')]
        self.assertEqual(len(sch.merge_same_task(rows)), 2)
        self.assertEqual(len(sch.merge_same_task([row('수확', 3, '상', 3, '상'), row('수확', 3, '중', 5, '하')])), 1)

    def test_forwarded_for_header_does_not_bypass_glossary_limit(self):
        with mock.patch('farming.views.GlossaryThrottle.THROTTLE_RATES', {'glossary': '2/min'}, create=True), \
                mock.patch('farming.glossary.lookup', return_value={'term': 'x', 'found': False}):
            codes = [APIClient().get('/api/farming/glossary', {'q': 'x'}, HTTP_X_FORWARDED_FOR=f'1.2.3.{i}').status_code
                     for i in range(3)]
        self.assertEqual(codes, [200, 200, 429])
