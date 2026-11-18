"""rag/llm.py 제공사 나누기 테스트 (GMS의 OpenAI·Gemini 형식). 실제 호출 없이 httpx를 가짜로 바꾼다."""
import json
from contextlib import contextmanager
from unittest import mock

import httpx
from django.test import SimpleTestCase, override_settings

from rag import llm

GMS = dict(GMS_KEY='test-key', GMS_OPENAI_URL='https://gms/openai', GMS_GEMINI_URL='https://gms/gemini')


def response(status=200, data=None):
    return httpx.Response(status, json=data or {}, request=httpx.Request('POST', 'https://gms/x'))


@contextmanager
def fake_stream(lines, status=200):
    res = mock.MagicMock(status_code=status)
    res.iter_lines.return_value = lines
    yield res


class ProviderTests(SimpleTestCase):
    def test_provider_by_model_name(self):
        self.assertEqual(llm.provider('claude-sonnet-5-5'), 'anthropic')
        self.assertEqual(llm.provider('gpt-4.1-mini'), 'openai')
        self.assertEqual(llm.provider('o4-mini'), 'openai')
        self.assertEqual(llm.provider('gemini-2.5-flash'), 'gemini')

    @override_settings(GMS_KEY=None)
    def test_openai_and_gemini_need_gms_key(self):
        with self.assertRaises(llm.LlmError) as cm:
            llm.complete('s', [{'role': 'user', 'content': 'q'}], model='gpt-4.1-mini')
        self.assertEqual(cm.exception.kind, 'unavailable')


@override_settings(**GMS)
class OpenAiTests(SimpleTestCase):
    def test_complete_sends_system_message_and_reads_usage(self):
        data = {'choices': [{'message': {'content': ' 답 '}, 'finish_reason': 'stop'}],
                'usage': {'prompt_tokens': 12, 'completion_tokens': 3, 'prompt_tokens_details': {'cached_tokens': 4}}}
        with mock.patch('httpx.post', return_value=response(200, data)) as post:
            r = llm.complete('시스템', [{'role': 'user', 'content': '질문'}], max_tokens=50, model='gpt-4.1-mini')
        url, kw = post.call_args.args[0], post.call_args.kwargs
        self.assertEqual(url, 'https://gms/openai')
        self.assertEqual(kw['headers'], {'Authorization': 'Bearer test-key'})
        self.assertEqual(kw['json']['messages'][0], {'role': 'system', 'content': '시스템'})
        self.assertEqual(kw['json']['max_completion_tokens'], 50)
        self.assertEqual((r.text, r.input_tokens, r.output_tokens, r.cache_read_tokens, r.stop_reason),
                         ('답', 12, 3, 4, 'stop'))

    def test_stream_yields_deltas_then_done_with_usage(self):
        chunk = lambda text: 'data: ' + json.dumps({'choices': [{'delta': {'content': text}, 'finish_reason': None}]})
        lines = [chunk('안녕'), '', chunk('하세요'),
                 'data: ' + json.dumps({'choices': [], 'usage': {'prompt_tokens': 5, 'completion_tokens': 2}}),
                 'data: [DONE]']
        with mock.patch('httpx.stream', return_value=fake_stream(lines)) as st:
            out = list(llm.stream('s', [{'role': 'user', 'content': 'q'}], model='gpt-4.1-mini'))
        self.assertTrue(st.call_args.kwargs['json']['stream'])
        self.assertEqual(out[:2], [('delta', '안녕'), ('delta', '하세요')])
        done = out[-1][1]
        self.assertEqual((done.text, done.input_tokens, done.output_tokens), ('안녕하세요', 5, 2))

    def test_status_errors_map_to_llm_error_kinds(self):
        for status, kind in ((429, 'rate_limit'), (400, 'bad_request'), (500, 'unavailable')):
            with mock.patch('httpx.post', return_value=response(status)):
                with self.assertRaises(llm.LlmError) as cm:
                    llm.complete('s', [{'role': 'user', 'content': 'q'}], model='gpt-4.1-mini')
            self.assertEqual(cm.exception.kind, kind)
        with mock.patch('httpx.post', side_effect=httpx.ReadTimeout('t')):
            with self.assertRaises(llm.LlmError) as cm:
                llm.complete('s', [{'role': 'user', 'content': 'q'}], model='gpt-4.1-mini')
        self.assertEqual(cm.exception.kind, 'timeout')


@override_settings(**GMS)
class GeminiTests(SimpleTestCase):
    def test_complete_maps_roles_and_turns_off_flash_thinking(self):
        data = {'candidates': [{'content': {'parts': [{'text': '생각', 'thought': True}, {'text': '{"a": 1}'}]},
                                'finishReason': 'STOP'}],
                'usageMetadata': {'promptTokenCount': 7, 'candidatesTokenCount': 2}}
        msgs = [{'role': 'user', 'content': 'q'}, {'role': 'assistant', 'content': 'x'}, {'role': 'user', 'content': 'again'}]
        with mock.patch('httpx.post', return_value=response(200, data)) as post:
            r = llm.complete('시스템', msgs, max_tokens=30, model='gemini-2.5-flash')
        url, kw = post.call_args.args[0], post.call_args.kwargs
        self.assertEqual(url, 'https://gms/gemini/gemini-2.5-flash:generateContent')
        self.assertEqual(kw['headers'], {'x-goog-api-key': 'test-key'})  # 키는 주소가 아니라 헤더로
        body = kw['json']
        self.assertEqual([c['role'] for c in body['contents']], ['user', 'model', 'user'])
        self.assertEqual(body['systemInstruction']['parts'][0]['text'], '시스템')
        self.assertEqual(body['generationConfig'], {'maxOutputTokens': 30, 'thinkingConfig': {'thinkingBudget': 0}})
        self.assertEqual((r.text, r.input_tokens, r.output_tokens), ('{"a": 1}', 7, 2))  # 생각 조각은 뺀다

    def test_complete_json_works_through_gemini(self):
        data = {'candidates': [{'content': {'parts': [{'text': '{"intent": "재배"}'}]}}]}
        with mock.patch('httpx.post', return_value=response(200, data)):
            parsed, results = llm.complete_json('s', 'q', model='gemini-2.5-flash-lite')
        self.assertEqual(parsed, {'intent': '재배'})
        self.assertEqual(len(results), 1)

    def test_stream_uses_sse_action(self):
        chunk = lambda text, n: 'data: ' + json.dumps({'candidates': [{'content': {'parts': [{'text': text}]}}],
                                                       'usageMetadata': {'promptTokenCount': 9, 'candidatesTokenCount': n}})
        with mock.patch('httpx.stream', return_value=fake_stream([chunk('1\n', 1), '', chunk('2', 2)])) as st:
            out = list(llm.stream('s', [{'role': 'user', 'content': 'q'}], model='gemini-2.5-pro'))
        self.assertEqual(st.call_args.args[1], 'https://gms/gemini/gemini-2.5-pro:streamGenerateContent?alt=sse')
        self.assertNotIn('thinkingConfig', st.call_args.kwargs['json']['generationConfig'])  # Pro는 생각을 끌 수 없다
        self.assertEqual([v for k, v in out if k == 'delta'], ['1\n', '2'])
        self.assertEqual((out[-1][1].input_tokens, out[-1][1].output_tokens), (9, 2))
