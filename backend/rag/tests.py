"""Y12 RAG 색인·검색 + LLM 모듈 테스트 (REQ-NFR-008, REQ-NFR-011, REQ-CHT-005 일부).

외부 API(Claude, NCPMS, 농사로)는 부르지 않는다. ES 검색 테스트는 rag_docs_test 인덱스를 쓰고, ES가 꺼져 있으면 건너뛴다.
임베딩 모델은 올리지 않고 가짜 벡터를 쓴다.
"""
import json
import unittest
from types import SimpleNamespace
from unittest import mock

import anthropic
from django.test import SimpleTestCase, override_settings

from rag import crops, llm, store
from rag.dose_filter import DOSE_TOKEN, mask_text
from rag.sources import ncpms
from rag.sources.nongsaro_clean import strip_private, to_record
from rag.text import CHUNK_SIZE, chunk_text, chunks_for_doc


class ChunkTests(SimpleTestCase):
    def test_short_text_is_one_chunk(self):
        self.assertEqual(chunk_text('첫 줄\n\n둘째 줄'), ['첫 줄\n둘째 줄'])

    def test_chunks_stay_under_size_and_overlap(self):
        lines = [f'{i}번 문단입니다. ' + '가' * 150 for i in range(12)]
        chunks = chunk_text('\n'.join(lines))
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(c) <= CHUNK_SIZE for c in chunks))
        # 앞 조각의 끝부분이 다음 조각 앞에 다시 들어간다 (겹침)
        self.assertTrue(chunks[0].endswith(chunks[1].split('\n')[0]))
        self.assertGreater(len(chunks[1].split('\n')[0]), 50)

    def test_long_line_is_split(self):
        chunks = chunk_text('가' * (CHUNK_SIZE * 2 + 10))
        self.assertEqual(len(chunks), 3)
        self.assertTrue(all(len(c) <= CHUNK_SIZE for c in chunks))

    def test_chunk_ids_and_title_header(self):
        doc = {'doc_id': 'd1', 'source_type': 'ncpms_pest', 'source_label': 'NCPMS', 'title': '사과 탄저병',
               'crop_names': ['사과'], 'text': '본문'}
        [c] = chunks_for_doc(doc)
        self.assertEqual(c['chunk_id'], 'd1:0')
        self.assertTrue(c['text'].startswith('[사과 탄저병]\n'))


class DoseMaskTests(SimpleTestCase):
    """REQ-CHT-005: 약제 사용량 문장은 "[사용량: 등록 기준 확인]"으로 바뀐다"""

    def test_pesticide_dose_is_masked(self):
        text, changes = mask_text('만코제브 수화제를 물 20L당 40g 희석하여 살포한다.')
        self.assertIn(DOSE_TOKEN, text)
        self.assertNotIn('40g', text)
        self.assertIn('만코제브 수화제', text)  # 약제 이름은 남긴다
        self.assertEqual(len(changes), 1)

    def test_fertilizer_amount_is_kept(self):
        text, changes = mask_text('퇴비는 10a당 2,000kg을 넣는다.')
        self.assertEqual(changes, [])
        self.assertIn('2,000kg', text)


class CropTests(SimpleTestCase):
    def test_crop_name_alias_parenthesis_and_skip(self):
        self.assertEqual(crops.crop_name('풋고추'), '고추')
        self.assertEqual(crops.crop_name('셀러리(양미나리)'), '셀러리')
        self.assertIsNone(crops.crop_name('기타'))

    def test_find_crops_in_question(self):
        known = ['배', '배추', '사과', '감']
        self.assertEqual(crops.find_crops('배추 뿌리에 혹이 생겨요', known), ['배추'])
        self.assertEqual(crops.find_crops('서리 오면 배 과수원 어떻게 해요', known), ['배'])
        self.assertEqual(crops.find_crops('홍로 잎에 반점이 생겨요', known), ['사과'])
        self.assertEqual(crops.find_crops('감자 심는 시기', known), [])  # "감자"의 "감"은 아님


class RrfTests(SimpleTestCase):
    def test_item_in_both_lists_ranks_first(self):
        fused = store.rrf_fuse([['a', 'b', 'c'], ['c', 'a', 'd']])
        self.assertEqual([cid for cid, _ in fused][:2], ['a', 'c'])
        self.assertAlmostEqual(fused[0][1], 1 / 61 + 1 / 62)

    def test_index_body_uses_nori_and_vector_dims(self):
        body = store.index_body()
        self.assertEqual(body['settings']['analysis']['tokenizer']['ko_tok']['type'], 'nori_tokenizer')
        self.assertEqual(body['mappings']['properties']['vector']['dims'], 384)


def _fake_message(text='답변', inp=100, out=20, cache_read=0):
    return SimpleNamespace(
        content=[SimpleNamespace(type='text', text=text)], stop_reason='end_turn',
        usage=SimpleNamespace(input_tokens=inp, output_tokens=out, cache_read_input_tokens=cache_read,
                              cache_creation_input_tokens=0))


class LlmTests(SimpleTestCase):
    """REQ-NFR-011: 설정값만 바꿔 다른 모델로 답한다. REQ-NFR-008: 같은 프롬프트는 캐싱한다"""

    def setUp(self):
        self.client = mock.Mock()
        patcher = mock.patch.object(llm, 'get_client', return_value=self.client)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_default_model_is_haiku_with_cached_system_prompt(self):
        self.client.messages.create.return_value = _fake_message(cache_read=900)
        result = llm.complete('시스템', [{'role': 'user', 'content': '질문'}])
        kwargs = self.client.messages.create.call_args.kwargs
        self.assertEqual(kwargs['model'], 'claude-haiku-5-5')
        self.assertEqual(kwargs['system'][0]['cache_control'], {'type': 'ephemeral'})
        self.assertEqual(kwargs['thinking'], {'type': 'disabled'})
        self.assertEqual((result.text, result.input_tokens, result.output_tokens, result.cache_read_tokens),
                         ('답변', 100, 20, 900))
        self.assertGreaterEqual(result.latency_ms, 0)

    @override_settings(LLM_MODEL='claude-sonnet-5-5')
    def test_model_changes_by_setting_only(self):
        self.client.messages.create.return_value = _fake_message()
        llm.complete('시스템', [{'role': 'user', 'content': '질문'}])
        kwargs = self.client.messages.create.call_args.kwargs
        self.assertEqual(kwargs['model'], 'claude-sonnet-5-5')
        self.assertNotIn('thinking', kwargs)  # Sonnet 5.5는 thinking 끄기가 400이라 effort로 줄인다
        self.assertEqual(kwargs['output_config'], {'effort': 'low'})

    def test_rate_limit_becomes_llm_error(self):
        response = mock.Mock(status_code=429, headers={})
        self.client.messages.create.side_effect = anthropic.RateLimitError('limit', response=response, body=None)
        with self.assertRaises(llm.LlmError) as ctx:
            llm.complete('시스템', [{'role': 'user', 'content': '질문'}])
        self.assertEqual(ctx.exception.kind, 'rate_limit')

    def test_complete_json_retries_once_on_bad_json(self):
        self.client.messages.create.side_effect = [_fake_message('JSON 아님'), _fake_message('{"intent": "재배"}')]
        data, results = llm.complete_json('시스템', '질문')
        self.assertEqual(data, {'intent': '재배'})
        self.assertEqual(len(results), 2)

    def test_stream_yields_deltas_then_result(self):
        stream_cm = mock.MagicMock()
        stream_cm.__enter__.return_value.text_stream = iter(['가', '나'])
        stream_cm.__enter__.return_value.get_final_message.return_value = _fake_message('가나')
        self.client.messages.stream.return_value = stream_cm
        events = list(llm.stream('시스템', [{'role': 'user', 'content': '질문'}]))
        self.assertEqual(events[:2], [('delta', '가'), ('delta', '나')])
        self.assertEqual(events[2][0], 'done')
        self.assertEqual(events[2][1].output_tokens, 20)


class SourceTests(SimpleTestCase):
    def test_ncpms_detail_to_doc_masks_dose(self):
        svc = {'symptoms': '열매에 둥근 갈색 반점<br/>움푹 들어간다',
               'preventionMethod': '베노밀 수화제 1,000배액을 살포한다.'}
        doc = ncpms.to_doc('사과', '병', 'D1', '탄저병', svc)
        self.assertEqual(doc['crop_names'], ['사과'])
        self.assertIn('[증상]\n열매에 둥근 갈색 반점\n움푹 들어간다', doc['text'])
        self.assertIn(DOSE_TOKEN, doc['text'])
        self.assertNotIn('1,000배액', doc['text'])

    def test_ncpms_empty_detail_is_skipped(self):
        self.assertIsNone(ncpms.to_doc('사과', '병', 'D1', '탄저병', {'etc': '기타'}))

    def test_fieldtech_drops_person_and_sub_address(self):
        text, changed = strip_private('- 장 소 : 경북 청송군 부남면 대전2길 26-37\n- 출장자 : 홍길동\n- 내용')
        self.assertEqual(text, '- 장 소 : 경북 청송군\n- 내용')
        self.assertEqual(changed, 2)
        rec = to_record({'cntntsNo': '1', 'cntntsSj': '사과 현장', 'cn': '<p class="title">조사</p><li>잎 반점</li>',
                         'wrterNm': '홍길동'})
        self.assertNotIn('wrterNm', rec)
        self.assertIn('## 조사', rec['text'])


@override_settings(RAG_INDEX='rag_docs_test')
class HybridSearchTests(SimpleTestCase):
    """ES 실제 검색: 작물로 거르고, 키워드·벡터 결과를 합친다"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        try:
            with override_settings(RAG_INDEX='rag_docs_test'):
                store.get_es().info()
        except Exception:
            raise unittest.SkipTest('Elasticsearch에 접속할 수 없다')

    def setUp(self):
        store.ensure_index(recreate=True)
        self.addCleanup(lambda: store.get_es().indices.delete(index='rag_docs_test', ignore_unavailable=True))

        def vec(i):
            v = [0.0] * 384
            v[i] = 1.0
            return v
        chunks = [
            {'chunk_id': 'a:0', 'doc_id': 'a', 'chunk_no': 0, 'source_type': 'ncpms_pest', 'source_label': 'N',
             'title': '사과 탄저병', 'text': '사과 열매에 둥근 갈색 반점이 생기고 움푹 들어간다', 'crop_names': ['사과']},
            {'chunk_id': 'b:0', 'doc_id': 'b', 'chunk_no': 0, 'source_type': 'ncpms_pest', 'source_label': 'N',
             'title': '사과 갈색무늬병', 'text': '잎에 갈색 무늬가 생기고 일찍 떨어진다', 'crop_names': ['사과']},
            {'chunk_id': 'c:0', 'doc_id': 'c', 'chunk_no': 0, 'source_type': 'ncpms_pest', 'source_label': 'N',
             'title': '고추 탄저병', 'text': '고추 열매에 둥근 반점이 생긴다', 'crop_names': ['고추']},
        ]
        store.index_chunks(chunks, [vec(0), vec(1), vec(0)])
        store.get_es().indices.refresh(index='rag_docs_test')
        self.vec = vec

    def test_crop_filter_excludes_other_crop(self):
        hits = store.hybrid_search(['열매 반점'], self.vec(0), crops=['사과'], size=5)
        self.assertEqual({h['crop_names'][0] for h in hits}, {'사과'})
        self.assertEqual(hits[0]['chunk_id'], 'a:0')

    def test_vector_only_and_keyword_only_both_work(self):
        by_vec = store.hybrid_search([], self.vec(1), crops=['사과'], size=1)
        self.assertEqual(by_vec[0]['chunk_id'], 'b:0')
        by_kw = store.hybrid_search(['갈색 무늬 떨어진다'], None, crops=['사과'], size=1)
        self.assertEqual(by_kw[0]['chunk_id'], 'b:0')
        self.assertNotIn('vector', by_kw[0])  # 응답에 벡터를 싣지 않는다

    def test_no_match_returns_empty_list(self):
        self.assertEqual(store.hybrid_search(['열매'], self.vec(0), crops=['딸기'], size=5), [])

    def test_common_doc_is_found_for_any_crop_but_other_crop_docs_are_not(self):
        v = self.vec(5)
        store.index_chunks([{'chunk_id': 'z:0', 'doc_id': 'z', 'chunk_no': 0, 'source_type': 'disaster',
                             'source_label': 'D', 'title': '재해예방 관리기술 정보', 'text': '서리 대비 관수 철저',
                             'crop_names': []}], [v])
        store.get_es().indices.refresh(index='rag_docs_test')
        for crop in ('사과', '딸기'):
            kw = store.hybrid_search(['서리 대비'], None, crops=[crop], size=5)
            self.assertEqual([h['chunk_id'] for h in kw], ['z:0'], crop)
            vec = store.hybrid_search([], v, crops=[crop], size=1)
            self.assertEqual(vec[0]['chunk_id'], 'z:0', crop)
        apple = store.hybrid_search(['열매 반점'], self.vec(0), crops=['사과'], size=5)
        self.assertNotIn('c:0', [h['chunk_id'] for h in apple])  # 고추 문서는 여전히 빠진다

    def test_delete_stale_removes_chunks_not_in_latest_index(self):
        deleted = store.delete_stale('ncpms_pest', ['a:0', 'c:0'])
        self.assertEqual(deleted, 1)
        self.assertEqual(store.count(), 2)

    def test_reindex_same_chunk_does_not_grow(self):
        store.index_chunks([{'chunk_id': 'a:0', 'doc_id': 'a', 'chunk_no': 0, 'source_type': 'ncpms_pest',
                             'source_label': 'N', 'title': '사과 탄저병', 'text': '수정', 'crop_names': ['사과']}],
                           [self.vec(0)])
        store.get_es().indices.refresh(index='rag_docs_test')
        self.assertEqual(store.count(), 3)


class ReviewFollowupTests(SimpleTestCase):
    """reviewer·tester 지적 보강"""

    def test_short_chunk_is_not_repeated_whole_in_next(self):
        # reviewer 예: 앞 조각이 짧고(100자) 다음 줄이 길다(600자). 어느 조각도 다른 조각 안에 통째로 들어 있지 않다
        chunks = chunk_text('가' * 100 + '\n' + '나' * 600 + '\n' + '다' * 300)
        for i, a in enumerate(chunks):
            for j, b in enumerate(chunks):
                if i != j:
                    self.assertNotIn(a, b)

    def test_more_dose_units_are_masked(self):
        for line in ['유제 1,000~2,000배로 희석해 살포', '액제를 물 20L에 20ml 타서 뿌린다', '입제 10a당 3kg 살포 (농약)',
                     '훈증제 50cc를 처리한다']:
            text, changes = mask_text(line)
            self.assertIn(DOSE_TOKEN, text, line)

    @override_settings(LLM_MODEL='claude-haiku-4-5')
    def test_unknown_model_gets_no_thinking_params(self):
        client = mock.Mock()
        client.messages.create.return_value = _fake_message()
        with mock.patch.object(llm, 'get_client', return_value=client):
            llm.complete('시스템', [{'role': 'user', 'content': '질문'}])
        kwargs = client.messages.create.call_args.kwargs
        self.assertNotIn('thinking', kwargs)
        self.assertNotIn('output_config', kwargs)


class FetcherTests(SimpleTestCase):
    def setUp(self):
        from rag.sources import http as h
        self.h = h
        self.f = h.Fetcher('test', 'AB+C/D=', interval=0)

    def test_mask_plain_and_encoded_key(self):
        text = self.f.mask('k=AB+C/D= q=AB%2BC%2FD%3D')
        self.assertNotIn('AB+C', text)
        self.assertNotIn('AB%2B', text)

    def test_retries_then_counts_calls(self):
        import urllib.error
        ok_resp = mock.MagicMock()
        ok_resp.__enter__.return_value.read.return_value = 'ok AB+C/D='.encode()
        err = urllib.error.HTTPError('u', 503, 'busy', {}, None)
        with mock.patch.object(self.h.urllib.request, 'urlopen', side_effect=[err, ok_resp]), \
                mock.patch.object(self.h.time, 'sleep'):
            body = self.f.get('http://x', {'apiKey': 'AB+C/D='})
        self.assertEqual(body, 'ok ***')
        self.assertEqual(self.f.calls, 2)

    def test_4xx_is_not_retried_and_message_has_no_key(self):
        import urllib.error
        err = urllib.error.HTTPError('http://x?apiKey=AB', 401, 'no', {}, None)
        with mock.patch.object(self.h.urllib.request, 'urlopen', side_effect=err):
            with self.assertRaises(self.h.SourceError) as ctx:
                self.f.get('http://x', {'apiKey': 'AB+C/D='})
        self.assertEqual(self.f.calls, 1)
        self.assertNotIn('AB', str(ctx.exception))


class CollectCommandTests(SimpleTestCase):
    """부분 수집: 오류 난 작물의 기존 문서는 지우지 않고, collect_log에 partial·호출 수를 남긴다"""

    def test_failed_crop_keeps_old_docs_and_logs_partial(self):
        from io import StringIO

        from django.core.management import call_command

        from chat.management.commands import rag_collect as cmd
        from rag.sources.http import CollectResult
        old = [{'doc_id': 'old_apple', 'crop_names': ['사과']}, {'doc_id': 'old_pear', 'crop_names': ['배']}]
        written, logs = {}, []
        fake = mock.Mock(return_value=CollectResult([{'doc_id': 'new_apple', 'crop_names': ['사과']}], 7,
                                                    done_crops=['사과'], errors=2))

        class FakeLog:
            def __init__(self, **kw):
                self.__dict__.update(kw)

            def save(self):
                logs.append(dict(self.__dict__))

        with mock.patch.dict(cmd.SOURCES, {'ncpms': ('rag_ncpms', fake, None)}), \
                mock.patch.object(cmd, 'read_docs', return_value=old), \
                mock.patch.object(cmd, 'write_docs', side_effect=lambda s, d: written.update({s: d})), \
                mock.patch.object(cmd, 'CollectLog', FakeLog):
            call_command('rag_collect', source='ncpms', crops='사과,배', stdout=StringIO())
        self.assertEqual([d['doc_id'] for d in written['ncpms']], ['old_pear', 'new_apple'])
        self.assertEqual((logs[0]['status'], logs[0]['api_calls'], logs[0]['row_count']), ('partial', 7, 1))

    def test_source_error_logs_calls_made(self):
        from io import StringIO

        from django.core.management import call_command

        from chat.management.commands import rag_collect as cmd
        from rag.sources.http import SourceError
        e = SourceError('ncpms HTTP 500')
        e.calls = 3
        logs = []

        class FakeLog:
            def __init__(self, **kw):
                self.__dict__.update(kw)

            def save(self):
                logs.append(dict(self.__dict__))

        with mock.patch.dict(cmd.SOURCES, {'ncpms': ('rag_ncpms', mock.Mock(side_effect=e), None)}), \
                mock.patch.object(cmd, 'CollectLog', FakeLog), self.assertRaises(SystemExit):
            call_command('rag_collect', source='ncpms', crops='사과', stdout=StringIO(), stderr=StringIO())
        self.assertEqual((logs[0]['status'], logs[0]['api_calls']), ('fail', 3))


class IndexSkipTests(SimpleTestCase):
    def test_chunk_has_stable_text_hash(self):
        doc = {'doc_id': 'd', 'source_type': 'fieldtech', 'source_label': 'L', 'title': 'T', 'text': '본문'}
        self.assertEqual(chunks_for_doc(doc)[0]['text_hash'], chunks_for_doc(dict(doc))[0]['text_hash'])
        self.assertNotEqual(chunks_for_doc(doc)[0]['text_hash'],
                            chunks_for_doc({**doc, 'text': '바뀐 본문'})[0]['text_hash'])

    def test_rag_index_embeds_only_changed_chunks(self):
        from io import StringIO

        from django.core.management import call_command

        from chat.management.commands import rag_index as cmd
        docs = [{'doc_id': 'a', 'source_type': 'ncpms_pest', 'source_label': 'L', 'title': 'T', 'text': '같음'},
                {'doc_id': 'b', 'source_type': 'ncpms_pest', 'source_label': 'L', 'title': 'T', 'text': '새것'}]
        same_hash = chunks_for_doc(docs[0])[0]['text_hash']
        with mock.patch.object(cmd, 'read_docs', side_effect=lambda s: docs if s == 'ncpms' else []), \
                mock.patch.object(cmd.store, 'ensure_index'), \
                mock.patch.object(cmd.store, 'existing_hashes', return_value={'a:0': same_hash}), \
                mock.patch.object(cmd.store, 'index_chunks', side_effect=lambda c, v: len(c)) as put, \
                mock.patch.object(cmd.store, 'delete_stale', return_value=0), \
                mock.patch.object(cmd.store, 'get_es'), mock.patch.object(cmd.store, 'count', return_value=2), \
                mock.patch.object(cmd.embed, 'embed_passages', side_effect=lambda t: [[0.0]] * len(t)) as emb:
            call_command('rag_index', stdout=StringIO())
        self.assertEqual([c['chunk_id'] for c in put.call_args.args[0]], ['b:0'])
        self.assertEqual(len(emb.call_args.args[0]), 1)


# ---------- Y11: 재해예방정보·길잡이 목차 (REQ-COL-006, REQ-CHT-007) ----------

DISASTER_ROWS = [
    {'cntntsNo': '1', 'cntntsSj': '2026년 농작물 재해예방 관리기술 정보(제11호)', 'svcDtx': '2026-11-03',
     'rtnOrginlFileNm': 'a.pdf', 'rtnFileSeCode': '185001', 'rtnFileSn': '1', 'updusrEsntlNm': '홍길동'},
    {'cntntsNo': '2', 'cntntsSj': '2024년 농작물 재해예방 관리기술 정보(제12호)', 'svcDtx': '2024-12-02',
     'rtnOrginlFileNm': 'b.hwpx'},
    {'cntntsNo': '3', 'cntntsSj': '2024년 농작물 재해예방 관리기술 정보(제1호)', 'svcDtx': '2024-01-05',
     'rtnOrginlFileNm': 'c.hwpx'},                                   # 24개월보다 오래됨
    {'cntntsNo': '4', 'cntntsSj': '2026년 농작물 저온해(동해) 발생위험 예측 보고(3.27)', 'svcDtx': '2026-03-27',
     'rtnOrginlFileNm': 'd.pdf'},                                    # 정기 호가 아님
    {'cntntsNo': '5', 'cntntsSj': '2026년 농작물 재해예방 관리기술 정보(제10호)', 'svcDtx': '2026-10-05',
     'rtnOrginlFileNm': 'e.hwp'},                                    # 지원하지 않는 형식
]
BODY = '재해 대비 관리 ' * 40


class DisasterSourceTests(SimpleTestCase):
    def test_pick_rows_recent_regular_supported_only(self):
        import datetime

        from rag.sources import disaster
        picked, skipped = disaster.pick_rows(DISASTER_ROWS, datetime.date(2026, 11, 15))
        self.assertEqual([r['cntntsNo'] for r in picked], ['1', '2'])  # 최신순
        self.assertEqual(skipped, 1)

    def test_section_text_keeps_only_prevention_section(self):
        from rag.sources import disaster
        text = ('목차 Ⅱ.농작물 피해 예방 관리기술 1. 저온 Ⅲ. 참고자료 기상 전망 이번 달 날씨 '
                'Ⅱ 농작물 피해 예방 관리기술 서리 대비 방법 Ⅲ 참고자료 집필인 홍길동 전화 (063)238-1053')
        out = disaster.section_text(text)
        self.assertIn('서리 대비 방법', out)
        self.assertNotIn('이번 달 날씨', out)
        self.assertNotIn('홍길동', out)
        self.assertIsNone(disaster.section_text('표시 없는 본문'))  # 전체를 쓰면 집필진이 들어간다
        self.assertIsNone(disaster.to_doc(DISASTER_ROWS[0], '표시 없는 본문 ' * 100))

    def test_to_doc_is_common_doc_with_masks(self):
        from rag.sources import disaster
        row = DISASTER_ROWS[0]
        doc = disaster.to_doc(row, 'Ⅱ 농작물 피해 예방 관리기술 ○서리 대비 ○살균제 1,000배액 살포 문의 010-1234-5678 a@b.com ' + BODY)
        self.assertEqual(doc['crop_names'], [])  # 공통 문서
        self.assertEqual((doc['doc_id'], doc['source_type']), ('disaster_1', 'disaster'))
        self.assertIn('(2026-11-03)', doc['title'])
        self.assertIn(DOSE_TOKEN, doc['text'])
        self.assertNotIn('1,000배액', doc['text'])
        self.assertNotIn('010-1234-5678', doc['text'])
        self.assertNotIn('a@b.com', doc['text'])
        self.assertIn('\n○서리 대비', doc['text'])  # 항목 표시 앞에서 줄을 나눈다
        self.assertNotIn('홍길동', json.dumps(doc, ensure_ascii=False))  # 등록자 실명 필드는 안 쓴다
        self.assertNotIn('apiKey', doc['url'])
        self.assertIsNone(disaster.to_doc(row, '너무 짧다'))

    def test_collect_counts_calls_and_skips_bad_files(self):
        import datetime

        from rag.sources import disaster
        from rag.sources.doc_extract import ExtractError

        class FakeFetcher:
            calls = 0
            def get(self, url, params, cache_name=None, refresh=False):
                self.calls += 1
                rows = ''.join('<item>' + ''.join(f'<{k}>{v}</{k}>' for k, v in r.items()) + '</item>'
                               for r in DISASTER_ROWS[:2])
                return f'<response><header><resultCode>00</resultCode></header><body><items>{rows}</items></body></response>'
            def get_bytes(self, url, params, cache_file, refresh=False):
                self.calls += 1
                return b'%PDF-1.4' if params['cntntsNo'] == '1' else b'PK\x03\x04'
            def save(self, *a):
                pass

        texts = {'pdf': 'Ⅱ 농작물 피해 예방 관리기술 ' + BODY}

        def fake_extract(path, ext):
            if ext == 'hwpx':
                raise ExtractError('hwpx 추출 실패')
            return texts[ext]
        with mock.patch.object(disaster, 'extract', fake_extract):
            res = disaster._collect(FakeFetcher(), 'K', print, False, datetime.date(2026, 11, 15))
        self.assertEqual([d['doc_id'] for d in res.docs], ['disaster_1'])
        self.assertEqual((res.calls, res.errors), (3, 1))

    def test_rows_with_non_numeric_ids_are_dropped(self):
        from rag.sources import disaster
        self.assertTrue(disaster.valid_row({'cntntsNo': '271359', 'rtnFileSeCode': '185001', 'rtnFileSn': '1'}))
        self.assertFalse(disaster.valid_row({'cntntsNo': '../../x'}))
        self.assertFalse(disaster.valid_row({'cntntsNo': '1', 'rtnFileSn': '1&x=2'}))

    def test_phone_number_right_after_hangul_is_masked(self):
        from rag.sources import disaster
        doc = disaster.to_doc(DISASTER_ROWS[0], 'Ⅱ 농작물 피해 예방 관리기술 연락처063-238-1234 문의 ' + BODY)
        self.assertNotIn('238-1234', doc['text'])

    def test_collect_without_key_fails(self):
        from rag.sources import disaster
        with mock.patch.dict('os.environ', {'NONGSARO_API_KEY': ''}), self.assertRaises(disaster.SourceError):
            disaster.collect([])

    def test_hwpx_extract_reads_paragraph_text(self):
        import tempfile
        import zipfile

        from rag.sources.doc_extract import extract
        xml = ('<root xmlns:hp="x"><hp:p><hp:run><hp:t>서리 피해 예방</hp:t></hp:run></hp:p>'
               '<hp:p><hp:run><hp:t>관수 철저</hp:t></hp:run></hp:p></root>')
        with tempfile.NamedTemporaryFile(suffix='.hwpx') as f:
            with zipfile.ZipFile(f.name, 'w') as z:
                z.writestr('Contents/section0.xml', xml)
            self.assertEqual(extract(f.name, 'hwpx'), '서리 피해 예방\n관수 철저')

    def test_broken_file_is_extract_error(self):
        import tempfile

        from rag.sources.doc_extract import ExtractError, extract
        with tempfile.NamedTemporaryFile(suffix='.pdf') as f:
            f.write(b'not a pdf')
            f.flush()
            with self.assertRaises(ExtractError):
                extract(f.name, 'pdf')


class EbookSourceTests(SimpleTestCase):
    BOOKS = [
        {'ebookCode': '8', 'ebookName': '농업기술길잡이5_사과재배', 'stdItemNm': '사과', 'cropsEbookFileNo': '00001'},
        {'ebookCode': '90', 'ebookName': '농업기술길잡이90_사과', 'stdItemNm': '사과,기타과수', 'cropsEbookFileNo': '00001'},
        {'ebookCode': '9', 'ebookName': '식용버섯', 'stdItemNm': '양송이,표고버섯', 'cropsEbookFileNo': '00003'},
        {'ebookCode': '10', 'ebookName': '단고추', 'stdItemNm': '단고추(피망)', 'cropsEbookFileNo': '00004'},
    ]

    def test_latest_book_is_highest_code_with_exact_crop_name(self):
        from rag.sources import ebook
        self.assertEqual(ebook.latest_book(self.BOOKS, '사과')['ebookCode'], '90')
        self.assertEqual(ebook.latest_book(self.BOOKS, '표고버섯')['ebookCode'], '9')
        self.assertIsNone(ebook.latest_book(self.BOOKS, '고추'))  # "단고추(피망)"은 고추가 아니다

    def test_to_doc_adds_chapter_and_drops_registrant(self):
        from rag.sources import ebook
        rows = [{'indexName': '제8장 기상재해', 'indexLevel': '1', 'indexPage': '312', 'ebookUrl': 'http://www.nongsaro.go.kr/u1',
                 'registerEsntlNm': '홍길동'},
                {'indexName': '02 늦서리', 'indexLevel': '2', 'indexPage': '318', 'ebookUrl': 'http://www.nongsaro.go.kr/u2'}]
        doc = ebook.to_doc('사과', self.BOOKS[1], rows)
        self.assertEqual(doc['rows'][1]['chapter'], '제8장 기상재해')
        self.assertNotIn('registerEsntlNm', doc['rows'][0])
        self.assertEqual((doc['source_type'], doc['crop_names']), ('guide', ['사과']))
        self.assertNotIn('text', doc)  # 본문은 받지 않는다

    def test_only_nongsaro_urls_are_kept(self):
        from rag.sources import ebook
        rows = [{'indexName': 'a', 'indexLevel': '2', 'indexPage': '1', 'ebookUrl': 'javascript:alert(1)'},
                {'indexName': 'b', 'indexLevel': '2', 'indexPage': '2', 'ebookUrl': 'http://evil.example/x'},
                {'indexName': 'c', 'indexLevel': '2', 'indexPage': '3', 'ebookUrl': 'http://www.nongsaro.go.kr/p?x=1'}]
        urls = [r['ebookUrl'] for r in ebook.to_doc('사과', self.BOOKS[1], rows)['rows']]
        self.assertEqual(urls, ['', '', 'http://www.nongsaro.go.kr/p?x=1'])

    def test_non_numeric_file_no_is_an_error_not_a_cache_path(self):
        from rag.sources import ebook
        books = [{'ebookCode': '8', 'ebookName': 'B', 'stdItemNm': '사과', 'cropsEbookFileNo': '../x'}]
        with mock.patch.object(ebook, '_call', return_value=books):
            res = ebook._collect(mock.Mock(calls=1), 'K', ['사과'], print, False)
        self.assertEqual((res.docs, res.errors), ([], 1))

    def test_crop_without_guide_is_not_an_error(self):
        from rag.sources import ebook
        with mock.patch.object(ebook, '_call', return_value=self.BOOKS):
            res = ebook._collect(mock.Mock(calls=1), 'K', ['고추'], print, False)
        self.assertEqual((res.docs, res.done_crops, res.errors), ([], ['고추'], 0))


GUIDE_ROWS = [
    {'indexName': '제5장 재배 기술', 'indexLevel': '1', 'indexPage': '105', 'ebookUrl': 'http://www.nongsaro.go.kr/u5', 'chapter': '제5장 재배 기술'},
    {'indexName': '아주심기', 'indexLevel': '2', 'indexPage': '106', 'ebookUrl': 'http://www.nongsaro.go.kr/u6', 'chapter': '제5장 재배 기술'},
    {'indexName': '제7장 병해충 방제', 'indexLevel': '1', 'indexPage': '210', 'ebookUrl': 'http://www.nongsaro.go.kr/u7', 'chapter': '제7장 병해충 방제'},
    {'indexName': '탄저병', 'indexLevel': '2', 'indexPage': '212', 'ebookUrl': 'http://www.nongsaro.go.kr/u8', 'chapter': '제7장 병해충 방제'},
    {'indexName': '제8장 기상재해', 'indexLevel': '1', 'indexPage': '312', 'ebookUrl': 'http://www.nongsaro.go.kr/u9', 'chapter': '제8장 기상재해'},
    {'indexName': '늦서리', 'indexLevel': '2', 'indexPage': '318', 'ebookUrl': 'http://www.nongsaro.go.kr/u10', 'chapter': '제8장 기상재해'},
    {'indexName': '저온저장고 관리', 'indexLevel': '2', 'indexPage': '360', 'ebookUrl': 'http://www.nongsaro.go.kr/u11', 'chapter': '제10장 수확 후 관리'},
]


class GuideLinksTests(SimpleTestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path

        from rag import guide_links
        self.g = guide_links
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        (Path(tmp.name) / 'docs').mkdir()
        doc = {'doc_id': 'guide_사과', 'crop_names': ['사과'], 'title': '농업기술길잡이5_사과재배', 'rows': GUIDE_ROWS}
        (Path(tmp.name) / 'docs' / 'guide.jsonl').write_text(json.dumps(doc, ensure_ascii=False) + '\n', encoding='utf-8')
        cm = override_settings(RAG_DATA_DIR=Path(tmp.name))
        cm.enable()
        self.addCleanup(cm.disable)

    def test_weather_question_links_matching_item_with_url_and_page(self):
        links = self.g.links_for('사과', '날씨재해', '늦서리 피해 예방은 어떻게 하나요')
        self.assertEqual([(l['title'], l['page'], l['url']) for l in links], [('늦서리', 318, 'http://www.nongsaro.go.kr/u10')])
        self.assertEqual(links[0]['book'], '농업기술길잡이5_사과재배')

    def test_weather_role_ignores_items_outside_weather_chapters(self):
        links = self.g.links_for('사과', '날씨재해', '저온저장고 관리가 궁금해요')
        self.assertNotIn('저온저장고 관리', [l['title'] for l in links])
        self.assertEqual([l['title'] for l in links], ['제8장 기상재해'])  # 맞는 항목이 없으면 대표 장

    def test_pest_without_match_falls_back_to_chapter_and_max_two(self):
        links = self.g.links_for('사과', '병해충', '열매가 이상해요')
        self.assertEqual([l['title'] for l in links], ['제7장 병해충 방제'])
        links = self.g.links_for('사과', '병해충', '탄저병 증상', ['탄저병'])
        self.assertLessEqual(len(links), 2)
        self.assertEqual(links[0]['title'], '탄저병')

    def test_cultivation_uses_match_then_chapter(self):
        self.assertEqual([l['title'] for l in self.g.links_for('사과', '재배', '아주심기는 언제 해요')], ['아주심기'])
        self.assertEqual([l['title'] for l in self.g.links_for('사과', '재배', '뭘 해야 하나요')], ['제5장 재배 기술'])

    def test_three_or_more_candidates_are_cut_to_exactly_two(self):
        rows = [{'indexName': '제7장 병해충 방제', 'indexLevel': '1', 'indexPage': '210', 'ebookUrl': 'http://www.nongsaro.go.kr/u', 'chapter': '제7장 병해충 방제'}] + [
            {'indexName': n, 'indexLevel': '2', 'indexPage': str(p), 'ebookUrl': f'http://www.nongsaro.go.kr/u{p}', 'chapter': '제7장 병해충 방제'}
            for n, p in (('탄저병', 212), ('탄저병 방제 일정', 220), ('잎탄저병', 230), ('탄저병 약제', 240))]
        with mock.patch.object(self.g, 'guides', return_value={'사과': {'title': 'B', 'rows': rows}}):
            links = self.g.links_for('사과', '병해충', '탄저병이 걱정돼요')
        self.assertEqual(len(links), 2)
        self.assertEqual([l['page'] for l in links], [212, 220])  # 쪽 순

    def test_javascript_url_in_stored_guide_is_never_returned(self):
        rows = [{'indexName': '제7장 병해충 방제', 'indexLevel': '1', 'indexPage': '210', 'ebookUrl': 'javascript:x', 'chapter': '제7장 병해충 방제'}]
        with mock.patch.object(self.g, 'guides', return_value={'사과': {'title': 'B', 'rows': rows}}):
            self.assertEqual(self.g.links_for('사과', '병해충', '병해충'), [])

    def test_no_guide_crop_or_non_rag_role_gives_nothing(self):
        self.assertEqual(self.g.links_for('수박', '재배', '재배'), [])
        self.assertEqual(self.g.links_for('사과', '판매', '얼마에 팔까'), [])
        self.assertEqual(self.g.links_for(None, '재배', '재배'), [])


class CommonSourceCommandTests(SimpleTestCase):
    """rag_collect는 공통 출처(재해예방정보)를 통째로 바꾸고, 길잡이 목차는 색인하지 않는다"""

    def test_common_source_replaces_all_docs_on_success_and_keeps_only_failed_on_error(self):
        from io import StringIO

        from django.core.management import call_command

        from chat.management.commands import rag_collect as cmd
        from rag.sources.http import CollectResult
        old = [{'doc_id': 'disaster_old', 'crop_names': []}, {'doc_id': 'disaster_1', 'crop_names': []}]
        new = [{'doc_id': 'disaster_1', 'crop_names': []}]
        for errors, expect in ((0, ['disaster_1']), (1, ['disaster_old', 'disaster_1'])):
            written = {}
            fake = mock.Mock(return_value=CollectResult(new, 3, [], errors))

            class FakeLog:
                def __init__(self, **kw):
                    self.__dict__.update(kw)

                def save(self):
                    pass
            with mock.patch.dict(cmd.SOURCES, {'disaster': ('rag_disaster', fake, None)}), \
                    mock.patch.object(cmd, 'read_docs', return_value=old), \
                    mock.patch.object(cmd, 'write_docs', side_effect=lambda s, d: written.update({s: d})), \
                    mock.patch.object(cmd, 'CollectLog', FakeLog):
                call_command('rag_collect', source='disaster', crops='사과', stdout=StringIO())
            self.assertEqual([d['doc_id'] for d in written['disaster']], expect, errors)

    def test_common_source_with_zero_docs_keeps_old_docs(self):
        from io import StringIO

        from django.core.management import call_command

        from chat.management.commands import rag_collect as cmd
        from rag.sources.http import CollectResult
        logs, written = [], []

        class FakeLog:
            def __init__(self, **kw):
                self.__dict__.update(kw)

            def save(self):
                logs.append(dict(self.__dict__))
        with mock.patch.dict(cmd.SOURCES, {'disaster': ('rag_disaster', mock.Mock(return_value=CollectResult([], 1, [], 0)), None)}), \
                mock.patch.object(cmd, 'read_docs', return_value=[{'doc_id': 'old', 'crop_names': []}]), \
                mock.patch.object(cmd, 'write_docs', side_effect=lambda s, d: written.append(d)), \
                mock.patch.object(cmd, 'CollectLog', FakeLog):
            call_command('rag_collect', source='disaster', crops='사과', stdout=StringIO(), stderr=StringIO())
        self.assertEqual(written, [])  # 빈 결과로 옛 문서를 덮어쓰지 않는다
        self.assertEqual(logs[0]['status'], 'partial')

    def test_guide_is_collected_but_never_indexed(self):
        from chat.management.commands import rag_collect, rag_index
        self.assertIn('guide', rag_collect.SOURCES)
        self.assertNotIn('guide', rag_index.SOURCE_TYPES)
        self.assertEqual(rag_index.SOURCE_TYPES['disaster'], 'disaster')


QNA_VIEW = {'cntntsNo': '209159', 'cntntsSj': '사과 과수원 탄저병 방제 문의', 'regDt': '2018-10-01', 'wrterNm': '홍길동',
            'placeInfo': '경상남도 밀양시', 'questDtl': '<p>수확 직전인데 탄저병이 번집니다. 방법이 있을까요?</p>',
            'answerDtl': '<ul><li>- 병든 과실은 따내어 땅속 깊이 묻고, 살균제 1,000배액을 살포합니다.</li></ul>'
                         '<p>이 내용은 박영희연구사가 조사했습니다. 자세한 내용은 인증관리팀 김철수(☎063-238-1234, a@b.com)에게 '
                         '문의하시기 바랍니다. 담당 지도사와 상의하세요.</p>'}


def _qna_xml(items):
    rows = ''.join('<item>' + ''.join(f'<{k}><![CDATA[{v}]]></{k}>' for k, v in it.items()) + '</item>' for it in items)
    return f'<response><header><resultCode>00</resultCode></header><body><items>{rows}</items></body></response>'


class FieldQnaSourceTests(SimpleTestCase):
    """K49: 농사로 현장애로기술사례 (농가 질문·전문가 답변)"""

    def test_to_doc_finds_crop_and_drops_private_info(self):
        from rag.sources import fieldqna
        doc = fieldqna.to_doc(QNA_VIEW, ['사과', '배'])
        self.assertEqual((doc['doc_id'], doc['source_type'], doc['crop_names']), ('fieldqna_209159', 'fieldqna', ['사과']))
        self.assertTrue(doc['text'].startswith('(2018-10 처리된 상담 사례)\n[질문]\n'))
        self.assertIn('[답변]\n- 병든 과실은', doc['text'])
        dumped = json.dumps(doc, ensure_ascii=False)
        for private in ('홍길동', '밀양', '김철수', '박영희', '238-1234', 'a@b.com', '☎'):
            self.assertNotIn(private, dumped)             # 연락처가 든 문장은 통째로 지운다
        self.assertIn('이 내용은 연구사가 조사했습니다. 담당 지도사와 상의하세요.', doc['text'])  # 직함 앞 이름만 지운다
        self.assertIn(DOSE_TOKEN, doc['text'])
        self.assertNotIn('1,000배액', doc['text'])

    def test_to_doc_skips_post_without_known_crop(self):
        from rag.sources import fieldqna
        # 작물은 제목에서만 찾는다 (질문 본문의 "사과"는 보지 않는다). "차이점"의 "차"는 작물이 아니다
        self.assertIsNone(fieldqna.to_doc({**QNA_VIEW, 'cntntsSj': '산소 주위 칡 방제', 'questDtl': '사과밭 옆 칡'}, ['사과']))
        self.assertIsNone(fieldqna.to_doc({**QNA_VIEW, 'cntntsSj': '유정란과 무정란의 차이점'}, ['사과', '차']))
        self.assertIsNone(fieldqna.to_doc({**QNA_VIEW, 'answerDtl': '<p>짧다</p>'}, ['사과']))

    def test_collect_uses_recent_posts_only_and_failed_crop_is_not_done(self):
        from rag.sources import fieldqna
        rows = [{'cntntsNo': '1', 'cntntsSj': '사과 탄저병', 'regDt': '2018-10-01'},
                {'cntntsNo': '2', 'cntntsSj': '배 검은별무늬병', 'regDt': '2019-05-01'},
                {'cntntsNo': '3', 'cntntsSj': '사과 옛 글', 'regDt': '2012-01-02'},
                {'cntntsNo': '4', 'cntntsSj': '산소 주위 칡 방제', 'regDt': '2020-03-01'},
                {'cntntsNo': '../x', 'cntntsSj': '사과', 'regDt': '2020-01-01'}]

        class FakeFetcher:
            calls = 0
            def get(self, url, params, cache_name=None, refresh=False):
                self.calls += 1
                if url.endswith('List'):
                    return _qna_xml(rows)
                if params['cntntsNo'] == '2':
                    raise fieldqna.SourceError('fieldqna HTTP 500')
                return _qna_xml([{**QNA_VIEW, 'cntntsNo': params['cntntsNo']}])
            def save(self, *a):
                pass

        f = FakeFetcher()
        res = fieldqna._collect(f, 'K', ['사과', '배'], lambda m: None, False, None)
        # 2012년 글, 제목에 작물이 없는 글, 숫자가 아닌 번호는 상세를 부르지 않는다 (목록 1 + 상세 2)
        self.assertEqual([d['doc_id'] for d in res.docs], ['fieldqna_1'])
        self.assertEqual((res.calls, res.done_crops, res.errors), (3, ['사과'], 1))

    def test_collect_without_key_fails(self):
        from rag.sources import fieldqna
        with mock.patch.dict('os.environ', {'NONGSARO_WEEKFARM_KEY': ''}), self.assertRaises(fieldqna.SourceError):
            fieldqna.collect([])

    def test_source_is_collected_indexed_and_used_for_diagnosis(self):
        from chat.management.commands import rag_collect, rag_index
        from farming import diagnose
        self.assertIn('fieldqna', rag_collect.SOURCES)
        self.assertEqual(rag_index.SOURCE_TYPES['fieldqna'], 'fieldqna')
        self.assertIn('fieldqna', diagnose.SOURCE_TYPES)
