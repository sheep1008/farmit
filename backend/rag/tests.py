"""Y12 RAG 색인·검색 + LLM 모듈 테스트 (REQ-NFR-008, REQ-NFR-011, REQ-CHT-005 일부).

외부 API(Claude, NCPMS, 농사로)는 부르지 않는다. ES 검색 테스트는 rag_docs_test 인덱스를 쓰고, ES가 꺼져 있으면 건너뛴다.
임베딩 모델은 올리지 않고 가짜 벡터를 쓴다.
"""
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
