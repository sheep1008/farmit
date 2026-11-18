"""Y13 채팅 API 테스트 (REQ-CHT-001~005, 008, REQ-NFR-002, 008).

Claude·ES·임베딩은 부르지 않는다: rag.llm의 complete/stream, rag.retrieve.search를 가짜로 바꾼다.
"""
import json
from datetime import timedelta
from unittest import mock

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import UserProfile
from chat import prompts as P
from chat import service
from chat.models import ChatMessage, ChatSession
from codes.models import Item
from rag.dose_filter import DOSE_TOKEN
from rag.llm import LlmError, LlmResult

URL = '/api/chat/messages'


def sse(res):
    """SSE 본문 → [(event, data)]"""
    body = b''.join(res.streaming_content).decode()
    out = []
    for block in body.strip().split('\n\n'):
        lines = dict(line.split(': ', 1) for line in block.split('\n'))
        out.append((lines['event'], json.loads(lines['data'])))
    return out


def result(text='', inp=10, out=5):
    return LlmResult(text=text, model='claude-haiku-5-5', input_tokens=inp, output_tokens=out, latency_ms=3)


def classify_json(**kw):
    data = {'intent': '병해충', 'crop': '사과', 'queries': ['사과 탄저병'], 'volume_kg': None, 'desired_date': None}
    data.update(kw)
    return result(json.dumps(data, ensure_ascii=False))


def stream_of(text):
    def gen(system, messages, max_tokens=2048, model=None):
        for ch in [text[i:i + 7] for i in range(0, len(text), 7)]:
            yield 'delta', ch
        yield 'done', result(text, 100, 50)
    return gen


EVIDENCE = [
    {'n': 1, 'title': '사과 탄저병 (병)', 'source_label': 'NCPMS', 'source_type': 'ncpms_pest', 'url': '',
     'text': '열매에 둥근 갈색 반점', 'chunk_id': 'a:0', 'doc_id': 'a'},
    {'n': 2, 'title': '사과 갈색무늬병 (병)', 'source_label': 'NCPMS', 'source_type': 'ncpms_pest', 'url': '',
     'text': '잎에 갈색 무늬', 'chunk_id': 'b:0', 'doc_id': 'b'},
]


class ChatBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user('farmer', password='pw12345678!')
        UserProfile.objects.create(user=cls.user, sido='충남', sigungu='천안시')
        cls.other = User.objects.create_user('other', password='pw12345678!')
        UserProfile.objects.create(user=cls.other, sido='충남', sigungu='천안시')
        cls.apple = Item.objects.create(at_code='0601', name='사과', category='과일', is_forecast=True)
        cls.pear = Item.objects.create(at_code='0602', name='배', category='과일')

    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.client.force_login(self.user)
        p1 = mock.patch('rag.llm.complete')
        p2 = mock.patch('rag.llm.stream')
        p3 = mock.patch('rag.retrieve.search', return_value=EVIDENCE)
        self.complete, self.stream, self.search = p1.start(), p2.start(), p3.start()
        for p in (p1, p2, p3):
            self.addCleanup(p.stop)

    def ask(self, message, **extra):
        return self.client.post(URL, {'message': message, **extra}, format='json')


class AnswerFlowTests(ChatBase):
    def test_question_returns_intent_answer_and_cited_sources_only(self):
        """REQ-CHT-001·003: 판단된 역할과 답변, 인용된 근거만 출처로. 근거에 없는 번호는 지운다"""
        self.complete.return_value = classify_json()
        self.stream.side_effect = stream_of('탄저병일 수 있습니다.[근거 1][근거 9]\n잎 무늬는 다른 병입니다.[근거 2]\n')
        res = self.ask('사과 열매에 둥근 반점이 생겨요', item_id=self.apple.item_id)
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res['Content-Type'].startswith('text/event-stream'))
        ev = sse(res)
        names = [e for e, _ in ev]
        self.assertEqual(names[0], 'session')
        self.assertIn('status', names)  # REQ-CHT-006: 질문 즉시 진행 상태
        self.assertEqual(dict(ev)['intent'], {'intent': '병해충', 'intent_label': '병해충 상담'})
        done = dict(ev)['done']
        self.assertNotIn('[근거 9]', done['answer'])
        self.assertEqual([s['n'] for s in done['sources']], [1, 2])
        self.assertEqual(dict(ev)['sources']['sources'], done['sources'])
        self.assertTrue(done['answer'].endswith(P.DISCLAIMER))  # REQ-CHT-005 면책 문구
        streamed = ''.join(d['text'] for e, d in ev if e == 'delta')
        self.assertNotIn('[근거 9]', streamed)
        msg = ChatMessage.objects.get(pk=done['message_id'])
        self.assertEqual((msg.role, msg.intent, msg.input_tokens, msg.output_tokens), ('assistant', '병해충', 110, 55))
        self.assertIsNotNone(msg.latency_ms)

    def test_dose_sentence_is_replaced_even_while_streaming(self):
        """REQ-CHT-005: 약제 사용량 문장은 "[사용량: 등록 기준 확인]"으로 (스트리밍 중에도 숫자가 나오지 않게)"""
        self.complete.return_value = classify_json()
        self.stream.side_effect = stream_of('베노밀 수화제를 물 20L당 20g 희석해 살포합니다.[근거 1]\n')
        ev = sse(self.ask('탄저병 약은 얼마나 타요?', item_id=self.apple.item_id))
        streamed = ''.join(d['text'] for e, d in ev if e == 'delta')
        self.assertIn(DOSE_TOKEN, streamed)
        self.assertNotIn('20g', streamed)
        self.assertIn(DOSE_TOKEN, dict(ev)['done']['answer'])

    def test_out_of_scope_rule_answers_without_llm(self):
        """REQ-CHT-004: 범위 밖 질문은 LLM 호출 없이 안내"""
        ev = sse(self.ask('귀농 보조금 신청 방법 알려줘'))
        self.complete.assert_not_called()
        self.stream.assert_not_called()
        done = dict(ev)['done']
        self.assertEqual((done['intent'], done['answer'], done['sources']), ('범위밖', P.OUT_OF_SCOPE, []))

    def test_other_crop_question_is_guided_without_llm(self):
        """REQ-CHT-004: 선택 품목과 다른 품목 질문은 품목 변경 안내 (LLM 없음)"""
        ev = sse(self.ask('배 잎에 붉은 반점이 생겨요', item_id=self.apple.item_id))
        self.complete.assert_not_called()
        self.assertIn('품목을 배', dict(ev)['done']['answer'])

    def test_llm_out_of_scope_skips_answer_generation(self):
        self.complete.return_value = classify_json(intent='범위밖', queries=[])
        ev = sse(self.ask('오늘 점심 뭐 먹지'))
        self.stream.assert_not_called()
        self.search.assert_not_called()
        self.assertEqual(dict(ev)['done']['answer'], P.OUT_OF_SCOPE)

    def test_no_evidence_says_not_found_without_answer_llm(self):
        self.complete.return_value = classify_json()
        self.search.return_value = []
        ev = sse(self.ask('사과 이상한 증상', item_id=self.apple.item_id))
        self.stream.assert_not_called()
        self.assertTrue(dict(ev)['done']['answer'].startswith(P.NOT_FOUND))

    def test_llm_failure_sends_error_event(self):
        self.complete.side_effect = LlmError('unavailable', 'x')
        ev = sse(self.ask('사과 반점', item_id=self.apple.item_id))
        self.assertEqual(ev[-1], ('error', {'code': 'UPSTREAM_ERROR',
                                            'message': '답변을 만들지 못했습니다. 잠시 후 다시 시도해 주세요.'}))

    def test_same_question_is_served_from_cache(self):
        """REQ-NFR-002: 같은 질문 재요청은 캐시로 (LLM 다시 안 부름)"""
        self.complete.return_value = classify_json()
        self.stream.side_effect = stream_of('탄저병일 수 있습니다.[근거 1]\n')
        first = dict(sse(self.ask('사과 열매 반점', item_id=self.apple.item_id)))['done']
        calls = self.complete.call_count
        second = dict(sse(self.ask('사과 열매 반점', item_id=self.apple.item_id)))['done']
        self.assertEqual(self.complete.call_count, calls)
        self.assertTrue(second['cached'])
        self.assertEqual(second['answer'], first['answer'])


class SalesFlowTests(ChatBase):
    """REQ-CHT-002: "사과 어디서 팔까?" → 물량을 되묻고, 답하면 추천 결과를 설명"""

    def test_asks_volume_then_explains_recommendation(self):
        self.complete.return_value = classify_json(intent='판매', queries=[])
        ev = sse(self.ask('사과 어디서 팔까?', item_id=self.apple.item_id))
        done = dict(ev)['done']
        self.assertEqual(done['intent'], '판매')
        self.assertIn('물량', done['answer'])
        self.stream.assert_not_called()

        fake = (200, {'forecast_available': True, 'results': [{
            'rank': 1, 'market_id': '340101', 'market_name': '천안', 'target_week': '2026-11-16', 'pred_price': 3000.0, 'lower80': 2800.0,
            'upper80': 3200.0, 'net_won': 1500000, 'net_low_won': 1400000, 'net_high_won': 1600000,
            'transport_won': 0, 'storage_won': 0, 'is_closed': False, 'closed_dates': [], 'holiday_notice': None}]},
            {'volume_kg': 500.0, 'base_week': '2026-11-16', 'costs': {'transport_applied': False}})
        self.complete.return_value = classify_json(intent='판매', queries=[], volume_kg=500)
        self.stream.side_effect = stream_of('천안 시장이 1,500,000원으로 가장 많이 남습니다.[근거 1]\n')
        with mock.patch('chat.views._recommend', return_value=fake) as rec:
            ev = sse(self.ask('500kg', session_id=done['session_id'], item_id=self.apple.item_id))
        rec.assert_called_once()
        self.assertEqual(rec.call_args.args[2], 500)
        done2 = dict(ev)['done']
        self.assertIn('천안', done2['answer'])
        self.assertEqual(done2['sources'][0]['title'], '팜잇 판매 추천 계산')
        # 이전 대화가 역할 판단에 들어간다
        self.assertIn('사과 어디서 팔까?', self.complete.call_args.args[1][0]['content'])

    def test_no_forecast_is_explained_without_llm_answer(self):
        self.complete.return_value = classify_json(intent='판매', queries=[], volume_kg=100)
        with mock.patch('chat.views._recommend', return_value=(503, None, None)):
            ev = sse(self.ask('사과 100kg 어디서 팔까', item_id=self.apple.item_id))
        self.stream.assert_not_called()
        self.assertIn('예측이 아직', dict(ev)['done']['answer'])


class LimitAndAuthTests(ChatBase):
    def test_21st_question_is_limited(self):
        """REQ-NFR-008: 21번째 질문에 한도 안내 (429 CHAT_DAILY_LIMIT)"""
        s = ChatSession.objects.create(user=self.user, title='t')
        ChatMessage.objects.bulk_create([ChatMessage(session=s, role='user', content='q') for _ in range(20)])
        res = self.ask('사과 반점')
        self.assertEqual(res.status_code, 429)
        self.assertEqual(res.json()['error']['code'], 'CHAT_DAILY_LIMIT')
        self.assertIn('Retry-After', res)
        self.complete.assert_not_called()

    def test_staff_has_no_daily_limit(self):
        """관리자(is_staff)는 20번을 넘겨도 묻을 수 있고, 남은 횟수는 null"""
        self.user.is_staff = True
        self.user.save()
        s = ChatSession.objects.create(user=self.user, title='t')
        ChatMessage.objects.bulk_create([ChatMessage(session=s, role='user', content='q') for _ in range(20)])
        self.complete.return_value = classify_json()
        self.stream.side_effect = stream_of('탄저병일 수 있습니다.[근거 1]\n')
        ev = sse(self.ask('사과 반점'))
        self.assertIsNone(dict(ev)['session']['remaining_today'])
        self.assertIsNone(dict(ev)['done']['remaining_today'])
        self.assertIsNone(self.client.get('/api/users/me').json()['data']['chat_remaining_today'])

    def test_yesterday_questions_do_not_count(self):
        s = ChatSession.objects.create(user=self.user, title='t')
        ChatMessage.objects.bulk_create([ChatMessage(session=s, role='user', content='q') for _ in range(20)])
        ChatMessage.objects.filter(session=s).update(created_at=timezone.now() - timedelta(days=1))
        self.complete.return_value = classify_json(intent='범위밖', queries=[])
        res = self.ask('사과 반점')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(dict(sse(res))['session']['remaining_today'], 19)

    @override_settings(LLM_DAILY_LIMIT=1)
    def test_me_shows_remaining_today(self):
        self.complete.return_value = classify_json(intent='범위밖', queries=[])
        sse(self.ask('질문'))
        self.assertEqual(self.client.get('/api/users/me').json()['data']['chat_remaining_today'], 0)

    def test_requires_login(self):
        self.assertEqual(APIClient().post(URL, {'message': 'x'}, format='json').status_code, 401)

    def test_requires_csrf(self):
        c = APIClient(enforce_csrf_checks=True)
        c.force_login(self.user)
        res = c.post(URL, {'message': 'x'}, format='json')
        self.assertEqual((res.status_code, res.json()['error']['code']), (403, 'CSRF_FAILED'))

    def test_validation(self):
        self.assertEqual(self.ask('').status_code, 400)
        self.assertEqual(self.ask('x' * 1001).status_code, 400)
        self.assertEqual(self.ask('x', item_id=999999).status_code, 404)

    def test_other_users_session_is_404(self):
        s = ChatSession.objects.create(user=self.other, title='남의 대화')
        self.assertEqual(self.ask('x', session_id=s.id).status_code, 404)
        self.assertEqual(self.client.get(f'/api/chat/sessions/{s.id}').status_code, 404)


class HistoryTests(ChatBase):
    """REQ-CHT-008: 로그인한 회원은 이전 대화 목록을 볼 수 있다"""

    def test_sessions_list_and_detail(self):
        self.complete.return_value = classify_json()
        self.stream.side_effect = stream_of('탄저병일 수 있습니다.[근거 1]\n')
        done = dict(sse(self.ask('사과 열매 반점이 생겼어요', item_id=self.apple.item_id)))['done']
        ChatSession.objects.create(user=self.other, title='남의 대화')
        res = self.client.get('/api/chat/sessions').json()
        self.assertEqual(res['meta'], {'page': 1, 'size': 20, 'total': 1})
        self.assertEqual(res['data'][0]['title'], '사과 열매 반점이 생겼어요')
        detail = self.client.get(f"/api/chat/sessions/{done['session_id']}").json()['data']
        self.assertEqual([m['role'] for m in detail['messages']], ['user', 'assistant'])
        self.assertEqual(detail['messages'][1]['intent_label'], '병해충 상담')
        self.assertEqual(detail['messages'][1]['sources'][0]['n'], 1)
        self.assertTrue(detail['created_at'].endswith('+09:00'))

    def test_bad_page_params(self):
        self.assertEqual(self.client.get('/api/chat/sessions?size=500').status_code, 400)

    def test_user_delete_cascades_chat(self):
        ChatSession.objects.create(user=self.user, title='t')
        self.user.delete()
        self.assertEqual(ChatSession.objects.count(), 0)


class JosaTests(TestCase):
    def test_josa(self):
        self.assertEqual(P.josa('사과', '을', '를'), '사과를')
        self.assertEqual(P.josa('수박', '을', '를'), '수박을')
        self.assertEqual(P.josa('배', '으로', '로'), '배로')
        self.assertEqual(P.josa('귤', '으로', '로'), '귤로')
        self.assertEqual(P.josa('감귤', '은', '는'), '감귤은')


class LineFilterTests(TestCase):
    def test_cites_and_dose_per_line(self):
        f = service.LineFilter([1, 2])
        out = f.feed('가 [근거 1, 3]\n나 유제 1,000배액 살포') + f.flush()
        self.assertIn('[근거 1]', out)
        self.assertNotIn('3]', out)
        self.assertIn(DOSE_TOKEN, out)


class TesterFollowupTests(ChatBase):
    """tester 지적 보강: 오류 코드, 빈 목록, 정렬·페이지, 스트림 오류, 실제 추천 계산 경로"""

    def code(self, res):
        return res.status_code, res.json()['error']['code']

    def test_error_codes(self):
        anon = APIClient()
        self.assertEqual(self.code(anon.post(URL, {'message': 'x'}, format='json')), (401, 'NOT_AUTHENTICATED'))
        self.assertEqual(self.code(anon.get('/api/chat/sessions')), (401, 'NOT_AUTHENTICATED'))
        self.assertEqual(self.code(anon.get('/api/chat/sessions/1')), (401, 'NOT_AUTHENTICATED'))
        self.assertEqual(self.code(self.ask('')), (400, 'VALIDATION_ERROR'))
        self.assertEqual(self.code(self.ask('x', item_id=999999)), (404, 'NOT_FOUND'))
        self.assertEqual(self.code(self.ask('x', session_id=999999)), (404, 'NOT_FOUND'))
        self.assertEqual(self.code(self.client.get('/api/chat/sessions/999999')), (404, 'NOT_FOUND'))
        for q in ('size=500', 'size=0', 'page=0', 'page=abc'):
            self.assertEqual(self.code(self.client.get(f'/api/chat/sessions?{q}')), (400, 'INVALID_PARAMETER'), q)

    def test_limit_details_retry_after(self):
        s = ChatSession.objects.create(user=self.user, title='t')
        ChatMessage.objects.bulk_create([ChatMessage(session=s, role='user', content='q') for _ in range(20)])
        res = self.ask('질문')
        wait = res.json()['error']['details']['retry_after_seconds']
        self.assertTrue(0 < wait <= 86401)
        self.assertEqual(res['Retry-After'], str(wait))

    def test_empty_list(self):
        res = self.client.get('/api/chat/sessions').json()
        self.assertEqual((res['data'], res['meta']['total']), ([], 0))

    def test_list_is_latest_first_and_paged(self):
        for i in range(3):
            ChatSession.objects.create(user=self.user, title=f'대화{i}')
        res = self.client.get('/api/chat/sessions?size=2&page=2').json()
        self.assertEqual(res['meta'], {'page': 2, 'size': 2, 'total': 3})
        self.assertEqual([s['title'] for s in res['data']], ['대화0'])
        first = self.client.get('/api/chat/sessions?size=2').json()['data']
        self.assertEqual([s['title'] for s in first], ['대화2', '대화1'])

    def test_timeout_and_store_errors_keep_question_counted(self):
        from rag.store import StoreUnavailable
        self.complete.side_effect = LlmError('timeout', 'x')
        ev = sse(self.ask('사과 반점', item_id=self.apple.item_id))
        self.assertEqual(ev[-1][1]['code'], 'UPSTREAM_TIMEOUT')
        self.complete.side_effect = None
        self.complete.return_value = classify_json()
        self.search.side_effect = StoreUnavailable('ConnectionError')
        ev = sse(self.ask('사과 반점 2', item_id=self.apple.item_id))
        self.assertEqual(ev[-1][1]['code'], 'SERVICE_UNAVAILABLE')
        self.assertEqual(ChatMessage.objects.filter(session__user=self.user, role='user').count(), 2)
        self.assertEqual(ChatMessage.objects.filter(session__user=self.user, role='assistant').count(), 0)
        self.assertEqual(self.client.get('/api/users/me').json()['data']['chat_remaining_today'], 18)

    def test_disclaimer_only_on_answers_not_notices(self):
        ev = sse(self.ask('귀농 보조금 알려줘'))
        self.assertNotIn(P.DISCLAIMER, dict(ev)['done']['answer'])

    def test_sales_uses_real_recommendation_calculation(self):
        """판매 상담이 실제 compute_recommendation(Y08)을 거쳐 1순위 시장을 설명한다"""
        from codes.models import Market
        from prices.models import Forecast
        from prices.views import _today_kst
        m = Market.objects.create(market_id='340101', name='천안', sido='충남', lat=0, lng=0, is_collect=True)
        today = _today_kst()  # 컨테이너 시계(UTC)가 아니라 한국 날짜 기준 (월요일 0~9시 경계)
        week = today - timedelta(days=today.weekday())
        Forecast.objects.create(item=self.apple, market=m, base_week=week, horizon=1, target_week=week,
                                pred_price=3000, lower80=2800, upper80=3200, model_version='t',
                                created_at=timezone.now())
        self.complete.return_value = classify_json(intent='판매', queries=[], volume_kg=100)
        self.stream.side_effect = stream_of('천안이 좋습니다.[근거 1]\n')
        ev = sse(self.ask('사과 100kg 어디서 팔까', item_id=self.apple.item_id))
        done = dict(ev)['done']
        self.assertEqual(done['recommendation']['top'][0]['market_name'], '천안')
        self.assertEqual(done['recommendation']['top'][0]['net_won'], 300000)
        prompt = self.stream.call_args.args[1][0]['content']
        self.assertIn('1순위: 천안', prompt)
        self.assertIn('300,000원', prompt)


class SaleDaysTests(ChatBase):
    """REQ-CHT-002: 질문한 시장 결과만, 추천 주 안의 날짜는 그 시장의 최근 요일별 가격으로"""

    def setUp(self):
        super().setUp()
        from codes.models import Market, MarketClosure
        from prices.models import Forecast, SettlePrice
        from prices.views import _today_kst
        self.today = _today_kst()
        this_week = self.today - timedelta(days=self.today.weekday())
        self.week = this_week + timedelta(weeks=1)
        self.jeongeup = Market.objects.create(market_id='350402', name='정읍', sido='전북', lat=0, lng=0)
        cheonan = Market.objects.create(market_id='340101', name='천안', sido='충남', lat=0, lng=0)
        for m, price in ((self.jeongeup, 3000), (cheonan, 5000)):  # 천안이 전체 1순위
            Forecast.objects.create(item=self.apple, market=m, base_week=this_week, horizon=1, target_week=self.week,
                                    pred_price=price, lower80=price - 200, upper80=price + 200, model_version='t',
                                    created_at=timezone.now())
        # 정읍 최근 8주: 화요일 +10%, 목요일 +5%, 나머지(월·수·금·토) 기준가. 일요일은 거래 없음
        for w in range(1, 9):
            mon = this_week - timedelta(weeks=w)
            for wd, p in ((0, 1000), (1, 1100), (2, 1000), (3, 1050), (4, 1000), (5, 1000)):
                SettlePrice.objects.create(trade_date=mon + timedelta(days=wd), market=self.jeongeup, item=self.apple,
                                           grade='ALL', avg_price=p, min_price=p, max_price=p, volume_kg=100)
        # 다음 주 목요일은 휴장
        MarketClosure.objects.create(market=self.jeongeup, closure_date=self.week + timedelta(days=3))

    def test_market_in_question_keeps_only_that_market_and_picks_days(self):
        self.complete.return_value = classify_json(intent='판매', queries=[], volume_kg=100)
        self.stream.side_effect = stream_of('정읍에서 파세요.[근거 1]\n')
        ev = sse(self.ask('정읍 시장에서만 팔 건데 며칠에 파는 게 좋을지 날짜 3개 알려줘 100kg',
                          item_id=self.apple.item_id))
        done = dict(ev)['done']
        self.assertEqual([r['market_name'] for r in done['recommendation']['top']], ['정읍'])
        prompt = self.stream.call_args.args[1][0]['content']
        self.assertIn('정읍 시장 결과만', prompt)
        self.assertIn('농가가 날짜를 물었음: 예', prompt)
        self.assertNotIn('천안', prompt)
        tue, mon = self.week + timedelta(days=1), self.week
        self.assertIn(f'- 1. {tue.isoformat()}(화)', prompt)  # 화요일이 가장 높다
        self.assertNotIn(f'{(self.week + timedelta(days=3)).isoformat()}(목)', prompt)  # 휴장일 제외
        self.assertIn(f'{mon.isoformat()}(월)', prompt)  # 남은 날 중 가장 이른 날
        self.assertNotIn('(일)', prompt)  # 거래 없는 요일 제외

    def test_market_and_date_ask_from_earlier_question_are_used(self):
        """"정읍에서만, 며칠에 팔까?" 다음 "100kg"만 답해도 정읍으로 거르고 날짜를 물은 것으로 본다"""
        self.complete.return_value = classify_json(intent='판매', queries=[])
        first = dict(sse(self.ask('사과 정읍에서만 팔 건데 며칠에 팔까', item_id=self.apple.item_id)))['done']
        self.complete.return_value = classify_json(intent='판매', queries=[], volume_kg=100)
        self.stream.side_effect = stream_of('정읍.[근거 1]\n')
        done = dict(sse(self.ask('100kg', session_id=first['session_id'], item_id=self.apple.item_id)))['done']
        self.assertEqual([r['market_name'] for r in done['recommendation']['top']], ['정읍'])
        self.assertIn('농가가 날짜를 물었음: 예', self.stream.call_args.args[1][0]['content'])

    def test_without_market_uses_top_market_and_says_when_no_history(self):
        self.complete.return_value = classify_json(intent='판매', queries=[], volume_kg=100)
        self.stream.side_effect = stream_of('천안.[근거 1]\n')
        sse(self.ask('사과 100kg 어디서 팔까', item_id=self.apple.item_id))
        prompt = self.stream.call_args.args[1][0]['content']
        self.assertIn('1순위: 천안', prompt)
        self.assertIn('[추천 날짜] 천안 시장. 농가가 날짜를 물었음: 아니오', prompt)
        self.assertIn('날짜를 고르지 못했습니다', prompt)  # 천안 정산 기록 없음


class ReviewerFollowupTests(ChatBase):
    """reviewer 지적 보강"""

    def test_weather_forecast_words_go_to_classifier(self):
        self.complete.return_value = classify_json(intent='날씨재해', queries=['사과 서리 피해'])
        self.stream.side_effect = stream_of('방상팬을 켭니다.[근거 1]\n')
        ev = sse(self.ask('날씨 예보에 서리 온다는데 사과 어떻게 대비해요?', item_id=self.apple.item_id))
        self.complete.assert_called()
        self.assertEqual(dict(ev)['done']['intent'], '날씨재해')

    def test_tax_question_goes_to_classifier(self):
        self.complete.return_value = classify_json(intent='판매', queries=[])
        ev = sse(self.ask('세금 떼면 얼마 남아요?', item_id=self.apple.item_id))
        self.complete.assert_called()
        self.assertEqual(dict(ev)['done']['intent'], '판매')

    def test_nan_or_huge_volume_asks_again(self):
        for bad in ('NaN', 'Infinity', 1e12, -5):
            self.complete.return_value = result(
                '{"intent": "판매", "crop": "사과", "queries": [], "volume_kg": %s, "desired_date": null}' % bad)
            with mock.patch('chat.views._recommend') as rec:
                ev = sse(self.ask(f'사과 {bad} 팔래요', item_id=self.apple.item_id))
            rec.assert_not_called()
            self.assertIn('물량', dict(ev)['done']['answer'], bad)

    def test_unexpected_error_sends_internal_error_event(self):
        self.complete.return_value = classify_json()
        self.search.side_effect = RuntimeError('boom')
        with self.assertLogs('chat.views', level='ERROR'):
            ev = sse(self.ask('사과 반점', item_id=self.apple.item_id))
        self.assertEqual(ev[-1][1]['code'], 'INTERNAL_ERROR')

    def test_dose_in_next_sentence_is_masked(self):
        f = service.LineFilter([1])
        out = f.feed('만코제브 수화제를 쓰세요. 500배로 타서 뿌립니다.\n물 20L당 20g씩 뿌리세요.\n')
        self.assertNotIn('500배', out)
        self.assertNotIn('20g', out)

    def test_desired_week_row_is_included(self):
        rows = [{'rank': i, 'market_name': f'시장{i}', 'target_week': '2026-11-16', 'pred_price': 1.0, 'lower80': 1.0,
                 'upper80': 1.0, 'net_won': 100 - i, 'net_low_won': 0, 'net_high_won': 0, 'transport_won': 0,
                 'storage_won': 0, 'is_closed': False, 'closed_dates': [], 'holiday_notice': None,
                 'is_desired': i == 7} for i in range(1, 9)]
        text = service._sales_result_text({'forecast_available': True, 'results': rows},
                                          {'volume_kg': 1, 'base_week': 'x', 'costs': {'transport_applied': True}})
        self.assertIn('7순위: 시장7', text)
        self.assertIn('농가가 원한 판매 주', text)
        self.assertNotIn('8순위', text)


class GuideLinkFlowTests(ChatBase):
    """Y11 REQ-CHT-007: 재배·재해 답변 아래 원문 링크(최대 2개), 같은 질문 캐시에도 포함"""
    LINKS = [{'book': '농업기술길잡이5_사과재배', 'title': '제7장 병해충 방제', 'page': 210, 'url': 'http://x/7',
              'license': '농촌진흥청 농업기술길잡이, 공공누리 제4유형'}]

    def test_rag_answer_done_event_has_guide_links_and_cache_keeps_them(self):
        self.complete.return_value = classify_json()
        self.stream.side_effect = stream_of('탄저병일 수 있습니다.[근거 1]\n')
        with mock.patch('chat.service.guide.links_for', return_value=self.LINKS) as links:
            done = dict(sse(self.ask('사과 열매에 둥근 반점이 생겨요', item_id=self.apple.item_id)))['done']
            self.assertEqual(done['guide_links'], self.LINKS)
            self.assertEqual(links.call_args.args[:3], ('사과', '병해충', '사과 열매에 둥근 반점이 생겨요'))
            self.assertEqual(links.call_args.args[3], ['사과 탄저병'])  # 분류가 만든 검색어도 쓴다
            cached = dict(sse(self.ask('사과 열매에 둥근 반점이 생겨요', item_id=self.apple.item_id)))['done']
        self.assertTrue(cached['cached'])
        self.assertEqual(cached['guide_links'], self.LINKS)

    def test_notices_and_sales_have_no_guide_links(self):
        self.complete.return_value = classify_json(intent='범위밖')
        done = dict(sse(self.ask('오늘 점심 뭐 먹지', item_id=self.apple.item_id)))['done']
        self.assertNotIn('guide_links', done)
        self.complete.return_value = classify_json(intent='판매', volume_kg=None)
        done = dict(sse(self.ask('사과 팔까요', item_id=self.apple.item_id)))['done']
        self.assertNotIn('guide_links', done)

    def test_broken_guide_file_does_not_lose_the_answer(self):
        self.complete.return_value = classify_json()
        self.stream.side_effect = stream_of('탄저병일 수 있습니다.[근거 1]\n')
        with mock.patch('chat.service.guide.links_for', side_effect=ValueError('깨진 파일')):
            done = dict(sse(self.ask('사과 열매에 둥근 반점이 생겨요', item_id=self.apple.item_id)))['done']
        self.assertIn('탄저병', done['answer'])
        self.assertEqual(done['guide_links'], [])

    def test_crop_without_guide_gets_empty_list(self):
        self.complete.return_value = classify_json()
        self.stream.side_effect = stream_of('탄저병일 수 있습니다.[근거 1]\n')
        with mock.patch('rag.guide_links.guides', return_value={}):
            done = dict(sse(self.ask('사과 열매에 둥근 반점이 생겨요', item_id=self.apple.item_id)))['done']
        self.assertEqual(done['guide_links'], [])

    def test_real_matching_returns_at_most_two_links_for_chosen_crop(self):
        self.complete.return_value = classify_json(intent='날씨재해', queries=['사과 늦서리'])
        self.stream.side_effect = stream_of('서리 대비가 필요합니다.[근거 1]\n')
        doc = {'title': '농업기술길잡이5_사과재배', 'rows': [
            {'indexName': '제8장 기상재해', 'indexLevel': '1', 'indexPage': '312', 'ebookUrl': 'http://www.nongsaro.go.kr/u9', 'chapter': '제8장 기상재해'},
            {'indexName': '늦서리', 'indexLevel': '2', 'indexPage': '318', 'ebookUrl': 'http://www.nongsaro.go.kr/u10', 'chapter': '제8장 기상재해'}]}
        with mock.patch('rag.guide_links.guides', return_value={'사과': doc}):
            done = dict(sse(self.ask('사과 늦서리가 걱정돼요', item_id=self.apple.item_id)))['done']
        self.assertEqual([l['title'] for l in done['guide_links']], ['늦서리'])
        self.assertLessEqual(len(done['guide_links']), 2)


class PriceFlowTests(ChatBase):
    """REQ-CHT-009: "9월 14일 주에 왜 가격이 높았어?" → 그 무렵 가격·물량·명절·사건을 근거로 설명"""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        from datetime import date
        from decimal import Decimal

        from alerts.models import PastCase
        from codes.models import Holiday, Market
        from prices.models import SettlePrice
        cls.m1 = Market.objects.create(market_id='250001', name='대전오정', sido='대전', lat=36, lng=127, is_collect=True)
        cls.m2 = Market.objects.create(market_id='350201', name='정읍', sido='전북', lat=35, lng=126)
        # 8/17 주 ~ 9/28 주 월요일 거래. 9/14 주가 가격·물량 최고
        weeks = {'2026-08-17': (4200, 5000), '2026-08-24': (4100, 6000), '2026-08-31': (4250, 7000),
                 '2026-09-07': (4300, 9000), '2026-09-14': (4600, 12000), '2026-09-21': (3800, 3000),
                 '2025-09-15': (4000, 10000)}
        for d, (p, v) in weeks.items():
            for m in (cls.m1, cls.m2):
                SettlePrice.objects.create(trade_date=date.fromisoformat(d), market=m, item=cls.apple, grade='ALL',
                                           avg_price=Decimal(p), min_price=Decimal(p), max_price=Decimal(p),
                                           volume_kg=Decimal(v))
        for d in ('2026-09-24', '2026-09-25', '2026-09-26'):
            Holiday.objects.create(holiday_date=date.fromisoformat(d), name='추석')
        for m in (cls.m1, cls.m2):  # 같은 사건이 시장마다 들어 있다 → 근거에는 한 번만
            PastCase.objects.create(item=cls.apple, market=m, event_type='HEAT_WAVE', sido='경상북도',
                                    event_start=date(2026, 8, 22), event_end=date(2026, 8, 27),
                                    base_week=date(2026, 8, 17), base_price=Decimal(4200),
                                    detail={'share': 38.3, 'places': ['경상북도 안동시']}, computed_at=timezone.now())

    def test_build_collects_prices_holiday_and_events(self):
        from datetime import date

        from chat import price_context
        ev = price_context.build(self.apple, date(2026, 9, 16), '9월 14일 주에 왜 비쌌어?', date(2026, 11, 18))
        titles = [e['title'] for e in ev]
        self.assertIn('전국 공영도매시장 합계', titles[0])
        text = ev[0]['text']
        self.assertIn('2026-09-14 주: 4,600원/kg, 거래 물량 24.0톤 ← 물은 주', text)
        self.assertIn('가장 높았습니다', text)
        self.assertIn('거래 물량도 앞뒤', text)
        self.assertTrue(any('1년 전' in t for t in titles))
        hol = next(e for e in ev if e['title'] == '가까운 명절')
        self.assertIn('추석 연휴: 2026-09-24 ~ 2026-09-26 (물은 주 월요일로부터 10일 뒤)', hol['text'])
        events = next(e for e in ev if '사건' in e['title'])
        self.assertEqual(events['text'].count('폭염'), 1)
        self.assertEqual([e['n'] for e in ev], list(range(1, len(ev) + 1)))

    def test_market_name_in_question_uses_that_market(self):
        from datetime import date

        from chat import price_context
        ev = price_context.build(self.apple, date(2026, 9, 14), '정읍 9월 14일 주 가격', date(2026, 11, 18))
        self.assertIn('정읍 시장', ev[0]['title'])
        self.assertIn('4,600원/kg, 거래 물량 12.0톤', ev[0]['text'])

    def test_screen_market_is_used_when_question_has_no_market(self):
        self.complete.return_value = classify_json(intent='시세', queries=[], target_date='2026-09-14')
        self.stream.side_effect = stream_of('정읍 시장 기준입니다.[근거 1]\n')
        sse(self.ask('9월 14일 주에 왜 비쌌어?', item_id=self.apple.item_id, market_id='350201'))
        self.assertIn('정읍 시장', self.stream.call_args.args[1][0]['content'])
        res = self.ask('9월 14일 주에 왜 비쌌어?', item_id=self.apple.item_id, market_id='999999')
        self.assertEqual(res.status_code, 404)

    def test_no_trade_gives_empty_evidence_and_notice(self):
        self.complete.return_value = classify_json(intent='시세', queries=[], target_date='2024-01-08')
        ev = sse(self.ask('2024년 1월 8일 주에 왜 쌌어?', item_id=self.apple.item_id))
        done = dict(ev)['done']
        self.assertEqual(done['intent'], '시세')
        self.assertIn('거래 기록이 없어', done['answer'])
        self.stream.assert_not_called()

    def test_price_question_is_explained_with_price_sources(self):
        self.complete.return_value = classify_json(intent='시세', queries=[], target_date='2026-09-14')
        self.stream.side_effect = stream_of('추석 전 주라 가격과 물량이 모두 가장 높았습니다.[근거 1][근거 3]\n')
        ev = sse(self.ask('9월 14일 주에는 왜 이렇게 높은 가격이 형성되었어?', item_id=self.apple.item_id))
        done = dict(ev)['done']
        self.assertEqual(done['intent'], '시세')
        self.assertEqual(done['intent_label'], '시세 상담')
        self.assertEqual([s['n'] for s in done['sources']], [1, 3])
        self.assertEqual(done['sources'][0]['source_type'], 'price_fact')
        prompt = self.stream.call_args.args[1][0]['content']
        self.assertIn('2026-09-14 주', prompt)
        self.assertIn('추석', prompt)
        self.search.assert_not_called()  # RAG 문서 검색은 하지 않는다
        self.assertEqual(ChatMessage.objects.filter(intent='시세').count(), 1)

    def test_parse_target_moves_future_date_back_a_year(self):
        from datetime import date

        from chat import price_context
        today = date(2026, 3, 2)
        self.assertEqual(price_context.parse_target('2026-09-14', today), date(2025, 9, 14))
        self.assertEqual(price_context.parse_target('2026-02-02', today), date(2026, 2, 2))
        self.assertIsNone(price_context.parse_target('9월', today))
        # 질문에 연도가 없으면 분류기가 준 연도 대신 올해(오늘 이전) 날짜로
        nov = date(2026, 11, 18)
        self.assertEqual(price_context.parse_target('2025-09-14', nov, '9월 14일 주에 왜 비쌌어?'), date(2026, 9, 14))
        self.assertEqual(price_context.parse_target('2025-09-14', nov, '작년 9월 14일 주'), date(2025, 9, 14))
        self.assertEqual(price_context.default_target(date(2026, 11, 18)), date(2026, 11, 9))


class SellVerbIsNotCropTests(TestCase):
    """'팔다'의 활용(파는 게·파면)을 작물 '파'로 잡지 않는다 (2026-11-18 "어디서 파는게 좋을까?" → 다른 품목 안내 버그)"""

    def test_sell_verb(self):
        from rag import crops
        known = ['사과', '파', '배']
        self.assertEqual(crops.find_crops('2주 후에 어디서 파는게 좋을까?', known), [])
        self.assertEqual(crops.find_crops('언제 파면 좋아?', known), [])
        self.assertEqual(crops.find_crops('파는 언제 심어?', known), ['파'])
        self.assertEqual(crops.find_crops('사과 파는 곳', known), ['사과'])


class LlmCompareSummaryTests(TestCase):
    """llm_compare 요약: 역할 정확도·평균 시간·토큰·근거 인용(LLM이 답을 쓴 질문만)·오류"""

    def test_summarize(self):
        from chat.management.commands.llm_compare import summarize
        rows = [
            {'intent': '판매', 'ms': 1000, 'in': 10, 'out': 5, 'sources': 1, 'error': ''},
            {'intent': '재배', 'ms': 3000, 'in': 20, 'out': 0, 'sources': 0, 'error': ''},   # 되묻기: LLM 답변 없음
            {'intent': None, 'ms': 2000, 'in': 0, 'out': 0, 'sources': 0, 'error': 'timeout'},
        ]
        s = summarize(rows, ['판매', '병해충', '시세'])
        self.assertEqual(s, {'intent_ok': 1, 'n': 3, 'errors': 1, 'avg_ms': 2000, 'in': 30, 'out': 5,
                             'cited': 1, 'answered': 1})
