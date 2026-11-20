"""LLM 호출을 모은 모듈 (REQ-NFR-011). 모든 Claude 호출은 여기를 거친다.

- 모델은 settings.LLM_MODEL (기본 claude-haiku-5-5). 설정값만 바꾸면 다른 모델로 답한다
- 모델 이름 앞부분으로 제공사를 고른다: claude-* → Anthropic(SDK), gpt-*·o1·o3·o4 → OpenAI 형식, gemini-* → Gemini 형식.
  OpenAI·Gemini는 SSAFY GMS 프록시로만 부른다 (GMS_KEY 필요). 부르는 쪽(채팅·증상 진단)은 제공사를 몰라도 된다
- 시스템 프롬프트에 cache_control을 붙여 매번 같은 프롬프트를 캐싱한다 (REQ-NFR-008)
- 결과마다 입력·출력 토큰, 캐시 읽기 토큰, 응답 시간(ms)을 돌려준다. 저장은 부르는 쪽(chat_message)이 한다
- 키·주소는 settings.LLM_API_KEY·LLM_BASE_URL: GMS_KEY가 있으면 SSAFY GMS 프록시, 없으면 ANTHROPIC_API_KEY로 직접.
  키·프롬프트 본문은 로그에 남기지 않는다
"""
import json
import logging
import re
import time
from dataclasses import dataclass

import anthropic
import httpx
from django.conf import settings

logger = logging.getLogger(__name__)

_client = None


class LlmError(Exception):
    """LLM 호출 실패. kind: rate_limit(잠시 후 재시도) | timeout | unavailable(키·네트워크·서버) | bad_request"""

    def __init__(self, kind, message):
        super().__init__(message)
        self.kind = kind


@dataclass
class LlmResult:
    text: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    latency_ms: int = 0
    stop_reason: str = ''


def get_client():
    global _client
    if _client is None:
        # GMS 프록시는 x-api-key 헤더에서만 키를 찾는다. 이 SDK는 키를 authorization 헤더로 보내므로 따로 붙인다
        headers = {'x-api-key': settings.LLM_API_KEY} if settings.LLM_BASE_URL and settings.LLM_API_KEY else None
        _client = anthropic.Anthropic(api_key=settings.LLM_API_KEY, base_url=settings.LLM_BASE_URL,
                                      default_headers=headers, timeout=settings.LLM_TIMEOUT_SECONDS, max_retries=1)
    return _client


def _model(model=None):
    return model or settings.LLM_MODEL


# effort를 받는 모델 (thinking을 끌 수 없는 5.x 세대). 목록에 없는 모델에는 thinking 관련 값을 보내지 않는다
EFFORT_MODELS = ('claude-opus-5', 'claude-sonnet-5', 'claude-fable-5')


def _thinking_params(model):
    """빠른 답이 필요해서 생각(thinking)을 줄인다.

    Haiku 5.5는 thinking을 끌 수 있다. Opus 5.5·Sonnet 5.5는 끄면 400이라 effort를 low로 낮춘다.
    그 밖의 모델은 기본값 그대로 둔다 (지원하지 않는 값을 보내 400이 나지 않게).
    """
    if model.startswith('claude-haiku-5'):
        return {'thinking': {'type': 'disabled'}}
    if model.startswith(EFFORT_MODELS):
        return {'output_config': {'effort': 'low'}}
    return {}


def _request(system, messages, max_tokens, model):
    return {
        'model': model,
        'max_tokens': max_tokens,
        # 시스템 프롬프트는 고정 문자열만 넣는다 (날짜 등 바뀌는 값을 넣으면 캐시가 깨진다)
        'system': [{'type': 'text', 'text': system, 'cache_control': {'type': 'ephemeral'}}],
        'messages': messages,
        **_thinking_params(model),
    }


def _result(message, model, started):
    usage = message.usage
    text = ''.join(b.text for b in message.content if getattr(b, 'type', '') == 'text')
    result = LlmResult(
        text=text.strip(), model=model,
        input_tokens=usage.input_tokens or 0, output_tokens=usage.output_tokens or 0,
        cache_read_tokens=getattr(usage, 'cache_read_input_tokens', 0) or 0,
        cache_write_tokens=getattr(usage, 'cache_creation_input_tokens', 0) or 0,
        latency_ms=int((time.monotonic() - started) * 1000), stop_reason=message.stop_reason or '',
    )
    logger.info('llm model=%s in=%s out=%s cache_read=%s cache_write=%s ms=%s stop=%s', model, result.input_tokens,
                result.output_tokens, result.cache_read_tokens, result.cache_write_tokens, result.latency_ms,
                result.stop_reason)
    return result


def _wrap(exc):
    """SDK 예외를 LlmError로 바꾼다. 메시지에 키·프롬프트가 들어가지 않게 종류만 남긴다."""
    if isinstance(exc, anthropic.RateLimitError):
        return LlmError('rate_limit', 'LLM 호출 한도 초과')
    if isinstance(exc, anthropic.BadRequestError):
        return LlmError('bad_request', 'LLM 요청 형식 오류')
    if isinstance(exc, anthropic.APIStatusError):
        return LlmError('unavailable', f'LLM 서버 오류 {exc.status_code}')
    if isinstance(exc, anthropic.APITimeoutError):  # APIConnectionError의 하위 클래스라 먼저 본다
        return LlmError('timeout', 'LLM 응답 시간 초과')
    if isinstance(exc, anthropic.APIConnectionError):
        return LlmError('unavailable', 'LLM 서버 접속 실패')
    return LlmError('unavailable', f'LLM 호출 실패 {type(exc).__name__}')


MAX_IMAGE_CHARS = 1_500_000   # data URL 전체 길이 (약 1.1MB 사진). 화면이 긴 변 1024px JPEG로 줄여 보낸다
_IMAGE_RE = re.compile(r'data:(image/(?:jpeg|png|webp));base64,([A-Za-z0-9+/]+={0,2})')


def parse_image(data_url):
    """화면이 보낸 사진 data URL → {'media_type', 'data'(base64)}. 형식이 다르면 None."""
    m = _IMAGE_RE.fullmatch(data_url)
    return {'media_type': m.group(1), 'data': m.group(2)} if m else None


def image_block(media_type, data):
    """사진 1장을 메시지 content에 넣는 조각 (base64). 사진 입력은 Claude 모델만 받는다."""
    return {'type': 'image', 'source': {'type': 'base64', 'media_type': media_type, 'data': data}}


def _text_only(messages):
    # OpenAI·Gemini 본문은 글자만 만든다. 사진이 든 메시지를 그대로 보내면 사진 없이 엉뚱한 답이 온다
    if any(not isinstance(m['content'], str) for m in messages):
        raise LlmError('bad_request', '사진 입력은 Claude 모델만 지원합니다')


def provider(model):
    """모델 이름 → 'anthropic' | 'openai' | 'gemini'"""
    if model.startswith('gemini'):
        return 'gemini'
    if model.startswith(('gpt', 'o1', 'o3', 'o4')):
        return 'openai'
    return 'anthropic'


def complete(system, messages, max_tokens=1024, model=None):
    """한 번에 답을 받는다. 반환: LlmResult"""
    model = _model(model)
    if provider(model) != 'anthropic':
        _text_only(messages)
        return _http_complete(system, messages, max_tokens, model)
    started = time.monotonic()
    try:
        message = get_client().messages.create(**_request(system, messages, max_tokens, model))
    except anthropic.AnthropicError as exc:
        raise _wrap(exc) from None
    return _result(message, model, started)


def stream(system, messages, max_tokens=2048, model=None):
    """답을 조각으로 받는다. ('delta', 글자 조각)을 차례로 내고, 마지막에 ('done', LlmResult)를 낸다."""
    model = _model(model)
    if provider(model) != 'anthropic':
        _text_only(messages)
        yield from _http_stream(system, messages, max_tokens, model)
        return
    started = time.monotonic()
    try:
        with get_client().messages.stream(**_request(system, messages, max_tokens, model)) as s:
            for text in s.text_stream:
                yield 'delta', text
            message = s.get_final_message()
    except anthropic.AnthropicError as exc:
        raise _wrap(exc) from None
    yield 'done', _result(message, model, started)


_JSON_RE = re.compile(r'\{.*\}', re.S)


def complete_json(system, user_text, max_tokens=512, model=None):
    """JSON 객체 하나를 답하게 한다. 형식이 틀리면 한 번 다시 묻는다. 반환: (dict 또는 None, [LlmResult])
    user_text는 글자, 또는 사진이 든 content 목록(image_block + text 조각)."""
    messages = [{'role': 'user', 'content': user_text}]
    results = []
    for _ in range(2):
        result = complete(system, messages, max_tokens=max_tokens, model=model)
        results.append(result)
        match = _JSON_RE.search(result.text)
        if match:
            try:
                data = json.loads(match.group(0))
                if isinstance(data, dict):
                    return data, results
            except json.JSONDecodeError:
                pass
        messages = messages + [
            {'role': 'assistant', 'content': result.text or '(빈 답)'},
            {'role': 'user', 'content': '설명 없이 JSON 객체 하나만 다시 출력하세요.'},
        ]
    return None, results


# ── OpenAI·Gemini (GMS 프록시, httpx로 직접 부른다) ─────────────────
# 키는 헤더로만 보낸다 (주소 쿼리에 넣으면 httpx 요청 로그에 키가 남는다)


def _http_target(model, stream):
    """(주소, 헤더)"""
    if not settings.GMS_KEY:
        raise LlmError('unavailable', f'{provider(model)} 모델은 GMS_KEY가 있어야 쓸 수 있습니다')
    if provider(model) == 'openai':
        return settings.GMS_OPENAI_URL, {'Authorization': f'Bearer {settings.GMS_KEY}'}
    action = 'streamGenerateContent?alt=sse' if stream else 'generateContent'
    return f'{settings.GMS_GEMINI_URL}/{model}:{action}', {'x-goog-api-key': settings.GMS_KEY}


def _openai_body(system, messages, max_tokens, model, stream):
    body = {'model': model, 'max_completion_tokens': max_tokens,
            'messages': [{'role': 'system', 'content': system}] + list(messages)}
    if stream:
        body.update(stream=True, stream_options={'include_usage': True})
    return body


def _gemini_body(system, messages, max_tokens, model):
    config = {'maxOutputTokens': max_tokens}
    # 2.5 Flash 계열은 생각을 끌 수 있다 (켜 두면 생각이 maxOutputTokens를 먼저 써서 답이 잘린다). Pro는 끌 수 없어 그대로
    if model.startswith('gemini-2.5-flash'):
        config['thinkingConfig'] = {'thinkingBudget': 0}
    return {'systemInstruction': {'parts': [{'text': system}]},
            'contents': [{'role': 'model' if m['role'] == 'assistant' else 'user', 'parts': [{'text': m['content']}]}
                         for m in messages],
            'generationConfig': config}


def _body(system, messages, max_tokens, model, stream):
    if provider(model) == 'openai':
        return _openai_body(system, messages, max_tokens, model, stream)
    return _gemini_body(system, messages, max_tokens, model)


def _usage(model, data):
    """응답(또는 스트림 조각)의 사용량 → (입력, 출력, 캐시 읽기)"""
    if provider(model) == 'openai':
        u = data.get('usage') or {}
        return (u.get('prompt_tokens') or 0, u.get('completion_tokens') or 0,
                (u.get('prompt_tokens_details') or {}).get('cached_tokens') or 0)
    u = data.get('usageMetadata') or {}
    return u.get('promptTokenCount') or 0, u.get('candidatesTokenCount') or 0, u.get('cachedContentTokenCount') or 0


def _text_and_stop(model, data):
    """응답(또는 스트림 조각) → (글자, 끝난 이유)"""
    if provider(model) == 'openai':
        choice = (data.get('choices') or [{}])[0]
        part = choice.get('delta') or choice.get('message') or {}
        return part.get('content') or '', choice.get('finish_reason') or ''
    cand = (data.get('candidates') or [{}])[0]
    parts = (cand.get('content') or {}).get('parts') or []
    # thought=true 조각(생각 요약)은 답이 아니다
    return ''.join(p.get('text', '') for p in parts if not p.get('thought')), cand.get('finishReason') or ''


def _http_result(model, text, usage, stop, started):
    result = LlmResult(text=text.strip(), model=model, input_tokens=usage[0], output_tokens=usage[1],
                       cache_read_tokens=usage[2], latency_ms=int((time.monotonic() - started) * 1000),
                       stop_reason=stop)
    logger.info('llm model=%s in=%s out=%s cache_read=%s ms=%s stop=%s', model, result.input_tokens,
                result.output_tokens, result.cache_read_tokens, result.latency_ms, result.stop_reason)
    return result


def _http_error(exc):
    """httpx 예외·상태 코드 → LlmError. 응답 본문은 남기지 않는다 (요청 내용이 들어 있을 수 있다)"""
    if isinstance(exc, httpx.TimeoutException):
        return LlmError('timeout', 'LLM 응답 시간 초과')
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        if code == 429:
            return LlmError('rate_limit', 'LLM 호출 한도 초과')
        if code == 400:
            return LlmError('bad_request', 'LLM 요청 형식 오류')
        return LlmError('unavailable', f'LLM 서버 오류 {code}')
    return LlmError('unavailable', f'LLM 서버 접속 실패 {type(exc).__name__}')


def _http_complete(system, messages, max_tokens, model):
    url, headers = _http_target(model, stream=False)
    started = time.monotonic()
    try:
        res = httpx.post(url, headers=headers, json=_body(system, messages, max_tokens, model, False),
                         timeout=settings.LLM_TIMEOUT_SECONDS)
        res.raise_for_status()
        data = res.json()
    except httpx.HTTPError as exc:
        raise _http_error(exc) from None
    text, stop = _text_and_stop(model, data)
    return _http_result(model, text, _usage(model, data), stop, started)


def _http_stream(system, messages, max_tokens, model):
    url, headers = _http_target(model, stream=True)
    started = time.monotonic()
    parts, usage, stop = [], (0, 0, 0), ''
    try:
        with httpx.stream('POST', url, headers=headers, json=_body(system, messages, max_tokens, model, True),
                          timeout=settings.LLM_TIMEOUT_SECONDS) as res:
            if res.status_code >= 400:
                res.read()
                res.raise_for_status()
            for line in res.iter_lines():
                if not line.startswith('data:'):
                    continue
                payload = line[5:].strip()
                if not payload or payload == '[DONE]':
                    continue
                data = json.loads(payload)
                text, finish = _text_and_stop(model, data)
                stop = finish or stop
                if any(_usage(model, data)):   # 사용량은 마지막 조각에 온다 (Gemini는 조각마다 누적값)
                    usage = _usage(model, data)
                if text:
                    parts.append(text)
                    yield 'delta', text
    except httpx.HTTPError as exc:
        raise _http_error(exc) from None
    yield 'done', _http_result(model, ''.join(parts), usage, stop, started)
